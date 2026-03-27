#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


HOST_PYTHON_DEFAULT = "/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"
SYSTEM_PYTHON_DEFAULT = "/usr/bin/python3"


@dataclass(frozen=True)
class SummaryHealth:
    fresh: bool
    reason: str
    age_seconds: float | None


class QuantLiveWatchdog:
    def __init__(self, output_base: Path) -> None:
        self.output_base = output_base
        self.repo_root = Path(__file__).resolve().parents[1]
        self.run_supervisor_script = Path(
            os.environ.get("QUANT_RUN_SUPERVISOR_SCRIPT", str(self.repo_root / "scripts" / "quant_run_live_orders.sh"))
        )
        self.check_interval_seconds = max(int(os.environ.get("QUANT_SUPERVISOR_WATCHDOG_INTERVAL_SECONDS", "60")), 1)
        self.stale_seconds = max(int(os.environ.get("QUANT_SUPERVISOR_WATCHDOG_STALE_SECONDS", "240")), 1)
        self.restart_cooldown_seconds = max(
            int(os.environ.get("QUANT_SUPERVISOR_WATCHDOG_RESTART_COOLDOWN_SECONDS", "45")),
            0,
        )
        self.startup_grace_seconds = max(int(os.environ.get("QUANT_LIVE_STARTUP_GRACE_SECONDS", "120")), 0)
        # Circuit breaker: pause watchdog restarts after too many in a short window
        self.max_restarts_per_window = max(int(os.environ.get("QUANT_WATCHDOG_MAX_RESTARTS_PER_WINDOW", "5")), 1)
        self.restart_window_seconds = max(int(os.environ.get("QUANT_WATCHDOG_RESTART_WINDOW_SECONDS", "600")), 60)
        self.circuit_breaker_pause_seconds = max(int(os.environ.get("QUANT_WATCHDOG_CIRCUIT_BREAKER_PAUSE_SECONDS", "900")), 60)
        self._restart_times: deque[float] = deque()
        self._circuit_broken_until: float = 0.0
        # Log rotation: rotate supervisor_log at this size (bytes), keep N backups
        self.log_max_bytes = max(int(os.environ.get("QUANT_WATCHDOG_LOG_MAX_BYTES", str(50 * 1024 * 1024))), 1024 * 1024)
        self.log_backup_count = max(int(os.environ.get("QUANT_WATCHDOG_LOG_BACKUP_COUNT", "5")), 1)
        self.python_bin = self._resolve_python_bin()
        self.log_dir = self.output_base
        self.supervisor_log = self.log_dir / "live_supervisor.log"
        self.supervisor_pid_path = self.log_dir / "live_supervisor.pid"
        self.watchdog_pid_path = self.log_dir / "live_supervisor_watchdog.pid"
        self.health_state_path = self.log_dir / "live_supervisor_health.json"
        self.summary_path = self.output_base / "output" / "paper-live-shell" / "latest" / "summary.state.json"
        self.started_at = time.time()
        digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]
        self.slot_version = f"v3:{digest}"
        self.self_pid = os.getpid()

    def _resolve_python_bin(self) -> str:
        requested = os.environ.get("PYTHON_BIN")
        for candidate in (requested, sys.executable, HOST_PYTHON_DEFAULT, SYSTEM_PYTHON_DEFAULT):
            if candidate and Path(candidate).exists() and os.access(candidate, os.X_OK):
                return str(candidate)
        raise RuntimeError("python interpreter unavailable for watchdog restarts")

    def _rotate_log_if_needed(self) -> None:
        try:
            if not self.supervisor_log.exists():
                return
            if self.supervisor_log.stat().st_size < self.log_max_bytes:
                return
            # Rotate: shift .1 → .2 → ... → .N (drop oldest), rename current → .1
            for i in range(self.log_backup_count - 1, 0, -1):
                src = self.supervisor_log.with_suffix(f".log.{i}" if i > 0 else "")
                if i == 1:
                    src = Path(str(self.supervisor_log) + ".1")
                dst = Path(str(self.supervisor_log) + f".{i + 1}")
                if src.exists():
                    src.rename(dst)
            self.supervisor_log.rename(Path(str(self.supervisor_log) + ".1"))
        except OSError:
            pass  # rotation failure is non-fatal

    def log(self, message: str) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._rotate_log_if_needed()
        with self.supervisor_log.open("a", encoding="utf-8") as handle:
            handle.write(f"[WATCHDOG] {message} at {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")

    def read_slot(self, path: Path) -> tuple[int | None, str | None]:
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None, None
        except OSError:
            return None, None
        if not raw:
            return None, None
        fields = raw.split()
        try:
            pid = int(fields[0])
        except (TypeError, ValueError):
            pid = None
        version = fields[1] if len(fields) > 1 else None
        return pid, version

    def write_slot(self, path: Path, version: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{self.self_pid} {version}\n", encoding="utf-8")

    def pid_alive(self, pid: int | None) -> bool:
        if pid is None or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def stop_pid(self, pid: int | None) -> None:
        if not self.pid_alive(pid):
            return
        assert pid is not None
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if not self.pid_alive(pid):
                return
            time.sleep(0.1)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return

    def owns_watchdog_slot(self) -> bool:
        current_pid, _ = self.read_slot(self.watchdog_pid_path)
        return current_pid == self.self_pid

    def within_startup_grace(self) -> bool:
        return (time.time() - self.started_at) < self.startup_grace_seconds

    def _file_health(self, path: Path, missing_reason: str, invalid_reason: str, stale_reason: str) -> SummaryHealth:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return SummaryHealth(fresh=False, reason=missing_reason, age_seconds=None)
        except (OSError, json.JSONDecodeError):
            return SummaryHealth(fresh=False, reason=invalid_reason, age_seconds=None)

        updated_at_raw = data.get("updated_at")
        if not isinstance(updated_at_raw, str):
            return SummaryHealth(fresh=False, reason=f"{invalid_reason}:missing_updated_at", age_seconds=None)

        try:
            updated_at = datetime.fromisoformat(updated_at_raw)
        except ValueError:
            return SummaryHealth(fresh=False, reason=f"{invalid_reason}:invalid_updated_at", age_seconds=None)

        age_seconds = max((datetime.now(timezone.utc) - updated_at).total_seconds(), 0.0)
        if age_seconds > self.stale_seconds:
            return SummaryHealth(fresh=False, reason=stale_reason, age_seconds=age_seconds)
        return SummaryHealth(fresh=True, reason="fresh", age_seconds=age_seconds)

    def summary_health(self) -> SummaryHealth:
        return self._file_health(
            self.summary_path,
            missing_reason="missing_summary_state",
            invalid_reason="invalid_summary_state",
            stale_reason="summary_state_stale",
        )

    def health_state_fresh(self) -> SummaryHealth:
        return self._file_health(
            self.health_state_path,
            missing_reason="missing_health_state",
            invalid_reason="invalid_health_state",
            stale_reason="health_state_stale",
        )

    def child_alive(self) -> bool:
        try:
            proc = subprocess.run(
                ["pgrep", "-f", f"quant_binance.runtime --mode live-auto-trade-daemon --exchange bitget --output-base {self.output_base}"],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return False
        return bool(proc.stdout.strip())

    def _check_circuit_breaker(self) -> bool:
        """Return True if circuit is broken (too many recent restarts). Prune stale times."""
        now = time.time()
        # If currently paused, check if pause expired
        if self._circuit_broken_until > now:
            remaining = int(self._circuit_broken_until - now)
            self.log(f"circuit breaker active; pausing restarts for {remaining}s more")
            return True
        # Prune times outside the window
        cutoff = now - self.restart_window_seconds
        while self._restart_times and self._restart_times[0] < cutoff:
            self._restart_times.popleft()
        if len(self._restart_times) >= self.max_restarts_per_window:
            self._circuit_broken_until = now + self.circuit_breaker_pause_seconds
            self.log(
                f"circuit breaker triggered: {len(self._restart_times)} restarts in "
                f"{self.restart_window_seconds}s window; pausing for {self.circuit_breaker_pause_seconds}s"
            )
            return True
        return False

    def restart_supervisor(self) -> None:
        if self._check_circuit_breaker():
            return

        env = os.environ.copy()
        env["PATH"] = "/Library/Frameworks/Python.framework/Versions/3.14/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        env["PYTHON_BIN"] = self.python_bin
        env["QUANT_TELEGRAM_NOTIFICATIONS"] = env.get("QUANT_TELEGRAM_NOTIFICATIONS", "0")
        env["QUANT_BYPASS_POLICY_GUARDRAILS"] = env.get("QUANT_BYPASS_POLICY_GUARDRAILS", "1")

        self._restart_times.append(time.time())
        self.log(
            f"restarting supervisor python_bin={self.python_bin} run_script={self.run_supervisor_script} "
            f"pwd={self.repo_root} (restart #{len(self._restart_times)} in window)"
        )
        with self.supervisor_log.open("ab") as handle:
            subprocess.Popen(
                ["/bin/sh", str(self.run_supervisor_script), str(self.output_base)],
                cwd=self.repo_root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        if self.restart_cooldown_seconds:
            time.sleep(self.restart_cooldown_seconds)

    def cleanup_slot(self, *_args: object) -> None:
        current_pid, _ = self.read_slot(self.watchdog_pid_path)
        if current_pid == self.self_pid:
            try:
                self.watchdog_pid_path.unlink()
            except FileNotFoundError:
                pass
        raise SystemExit(0)

    def claim_watchdog_slot(self) -> bool:
        existing_pid, existing_version = self.read_slot(self.watchdog_pid_path)
        if self.pid_alive(existing_pid) and existing_pid != self.self_pid:
            if existing_version == self.slot_version:
                self.log(f"existing watchdog pid={existing_pid} already running")
                return False
            self.log(
                f"replacing legacy watchdog pid={existing_pid} slot_version={existing_version or 'legacy'}"
            )
            self.stop_pid(existing_pid)
        self.write_slot(self.watchdog_pid_path, self.slot_version)
        return True

    def step(self) -> None:
        if not self.owns_watchdog_slot():
            current_pid, current_version = self.read_slot(self.watchdog_pid_path)
            self.log(f"watchdog slot lost to pid={current_pid} {current_version or ''}".strip())
            raise SystemExit(0)

        supervisor_pid, _ = self.read_slot(self.supervisor_pid_path)
        supervisor_alive = self.pid_alive(supervisor_pid)
        child_alive = self.child_alive()
        summary_health = self.summary_health()
        health_state = self.health_state_fresh()
        runtime_fresh = summary_health.fresh or health_state.fresh

        if child_alive and runtime_fresh:
            return

        if runtime_fresh:
            if child_alive:
                return
            self.log(f"child missing but runtime state still fresh; waiting summary={summary_health.reason} health={health_state.reason}")
            return

        combined_reason = f"summary={summary_health.reason},health={health_state.reason},child_alive={child_alive},supervisor_alive={supervisor_alive}"
        if self.within_startup_grace():
            self.log(f"{combined_reason} during startup grace; waiting")
            return

        if supervisor_alive:
            self.log(f"runtime stale/unhealthy; stopping supervisor pid={supervisor_pid} ({combined_reason})")
            self.stop_pid(supervisor_pid)
        else:
            self.log(f"runtime stale/unhealthy with missing supervisor ({combined_reason})")
        self.restart_supervisor()

    def run(self) -> int:
        if not self.claim_watchdog_slot():
            return 0

        signal.signal(signal.SIGINT, self.cleanup_slot)
        signal.signal(signal.SIGTERM, self.cleanup_slot)
        self.log(
            "watchdog started "
            f"pid={self.self_pid} interval={self.check_interval_seconds}s stale={self.stale_seconds}s "
            f"python_bin={self.python_bin} slot_version={self.slot_version}"
        )
        while True:
            self.step()
            time.sleep(self.check_interval_seconds)


def main(argv: list[str]) -> int:
    output_base = Path(argv[1] if len(argv) > 1 else "quant_runtime")
    watchdog = QuantLiveWatchdog(output_base=output_base)
    return watchdog.run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
