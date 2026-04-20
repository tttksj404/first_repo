#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
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
        # Strategy health check (every 5 min)
        self.strategy_check_interval_seconds = max(
            int(os.environ.get("QUANT_WATCHDOG_STRATEGY_CHECK_INTERVAL", "300")), 60
        )
        self.adopted_ratio_threshold = float(os.environ.get("QUANT_WATCHDOG_ADOPTED_RATIO_THRESHOLD", "0.90"))
        self.strategy_entry_lookback_hours = int(os.environ.get("QUANT_WATCHDOG_ENTRY_LOOKBACK_HOURS", "6"))
        self.equity_drop_threshold_pct = float(os.environ.get("QUANT_WATCHDOG_EQUITY_DROP_PCT", "5.0"))
        self._last_strategy_check: float = 0.0
        self._equity_history: deque[tuple[float, float]] = deque(maxlen=12)
        # Disk cleanup: run once at start then every 24h
        self._cleanup_interval_seconds = int(os.environ.get("QUANT_WATCHDOG_CLEANUP_INTERVAL_SECONDS", str(24 * 3600)))
        self._last_cleanup: float = 0.0
        self._disk_usage_mb: float = 0.0
        self.policy_state_path = self.output_base / "output" / "paper-live-shell" / "latest" / "policy_state.json"
        self.closed_trades_path = self.output_base / "output" / "paper-live-shell" / "latest" / "logs" / "closed_trades.jsonl"
        self.strategy_override_path = self.output_base / "artifacts" / "strategy_override.approved.json"
        self.strategy_health_path = self.log_dir / "health_status.json"

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

        status = str(data.get("status") or "")
        updated_at_raw = data.get("updated_at")
        if not isinstance(updated_at_raw, str):
            return SummaryHealth(fresh=False, reason=f"{invalid_reason}:missing_updated_at", age_seconds=None)

        try:
            updated_at = datetime.fromisoformat(updated_at_raw)
        except ValueError:
            return SummaryHealth(fresh=False, reason=f"{invalid_reason}:invalid_updated_at", age_seconds=None)

        age_seconds = max((datetime.now(timezone.utc) - updated_at).total_seconds(), 0.0)
        if status == "startup_failed":
            return SummaryHealth(fresh=False, reason="startup_failed", age_seconds=age_seconds)
        if status == "unhealthy":
            reason = str(data.get("reason") or "unhealthy")
            return SummaryHealth(fresh=False, reason=reason, age_seconds=age_seconds)
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

    # ------------------------------------------------------------------
    # Strategy health checks
    # ------------------------------------------------------------------

    def _load_json_safe(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_json_atomic(self, path: Path, data: dict) -> None:
        """Write JSON atomically via temp file + rename to avoid partial reads."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.rename(path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def _count_trades_by_source(self, path: Path) -> tuple[int, int]:
        """Stream-scan JSONL to count (total, adopted) without loading full file into memory."""
        total = 0
        adopted = 0
        try:
            with path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    total += 1
                    source = str(obj.get("source") or obj.get("entry_source") or "")
                    if source == "manual_exchange_external":
                        adopted += 1
        except OSError:
            pass
        return total, adopted

    def _load_jsonl_tail(self, path: Path, max_lines: int = 500) -> list[dict]:
        """Read only the last max_lines records from a JSONL file (memory-efficient)."""
        try:
            size = path.stat().st_size
        except OSError:
            return []
        # Estimate ~600 bytes/line; read 2x to ensure we capture max_lines full lines
        read_bytes = min(max_lines * 600 * 2, size)
        try:
            with path.open("rb") as fh:
                fh.seek(max(0, size - read_bytes))
                raw = fh.read().decode("utf-8", errors="replace")
        except OSError:
            return []
        lines = raw.splitlines()
        # Drop potentially partial first line when we seeked mid-file
        if size > read_bytes:
            lines = lines[1:]
        records = []
        for line in lines[-max_lines:]:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                records.append(obj)
        return records

    def _check_adopted_ratio(self) -> dict:
        total, adopted = self._count_trades_by_source(self.closed_trades_path)
        if total == 0:
            return {"severity": "OK", "message": "no trades yet", "value": 0.0}
        ratio = adopted / total
        if ratio >= self.adopted_ratio_threshold:
            return {
                "severity": "WARNING",
                "message": (
                    f"adopted ratio {ratio:.1%} >= {self.adopted_ratio_threshold:.0%} "
                    f"({adopted}/{total} trades); strategy data thin"
                ),
                "value": round(ratio, 4),
            }
        return {"severity": "OK", "message": f"adopted ratio {ratio:.1%}", "value": round(ratio, 4)}

    def _check_tighter_mode(self, policy_state: dict, current_force_mode: str) -> dict:
        auto_mode = dict(policy_state.get("auto_mode", {}) or {})
        mode = str(auto_mode.get("mode") or "")
        blocked = bool(auto_mode.get("expansion_blocked", False))
        reason_codes = list(auto_mode.get("reason_codes") or [])
        if mode == "tighter" and blocked:
            if current_force_mode == "normal":
                # force_auto_mode already active — policy computes tighter but session overrides to normal
                return {
                    "severity": "OK",
                    "message": (
                        f"policy computes tighter+blocked but force_auto_mode=normal is active; "
                        f"session running as normal. reasons={reason_codes}"
                    ),
                    "value": {"mode": mode, "expansion_blocked": blocked, "force_override": "normal"},
                }
            return {
                "severity": "WARNING",
                "message": (
                    f"auto_mode=tighter + expansion_blocked=True; strategy entries suppressed. "
                    f"reasons={reason_codes}"
                ),
                "value": {"mode": mode, "expansion_blocked": blocked},
            }
        return {
            "severity": "OK",
            "message": f"auto_mode={mode or 'unknown'} expansion_blocked={blocked}",
            "value": {"mode": mode, "expansion_blocked": blocked},
        }

    def _check_strategy_entries(self) -> dict:
        # Use tail read — only need recent records for time-window check
        recent_trades = self._load_jsonl_tail(self.closed_trades_path, max_lines=200)
        if not recent_trades:
            return {"severity": "OK", "message": "no trades yet", "value": 0}
        cutoff = time.time() - self.strategy_entry_lookback_hours * 3600
        recent_pure = 0
        for t in recent_trades:
            source = str(t.get("source") or t.get("entry_source") or "")
            if source == "manual_exchange_external":
                continue
            ts_raw = t.get("closed_at") or t.get("entry_time") or t.get("timestamp") or ""
            try:
                ts = datetime.fromisoformat(str(ts_raw)).timestamp() if ts_raw else 0.0
            except ValueError:
                ts = 0.0
            if ts >= cutoff:
                recent_pure += 1
        if recent_pure == 0:
            return {
                "severity": "WARNING",
                "message": f"0 pure strategy entries in last {self.strategy_entry_lookback_hours}h; entries fully stalled",
                "value": 0,
            }
        return {
            "severity": "OK",
            "message": f"{recent_pure} pure strategy entries in last {self.strategy_entry_lookback_hours}h",
            "value": recent_pure,
        }

    def _check_equity_drop(self, summary_state: dict) -> dict:
        # Use explicit None check — float 0.0 is valid equity and must not fall back
        equity_raw = summary_state.get("session_current_equity_usdt")
        if equity_raw is None:
            equity_raw = summary_state.get("session_start_equity_usdt")
        if equity_raw is None:
            return {"severity": "OK", "message": "equity data unavailable", "value": None}
        try:
            equity = float(equity_raw)
        except (TypeError, ValueError):
            return {"severity": "OK", "message": "equity parse error", "value": None}
        if equity <= 0.0:
            return {"severity": "OK", "message": f"equity={equity:.2f} (zero or negative, skip)", "value": None}
        now = time.time()
        self._equity_history.append((now, equity))
        if len(self._equity_history) < 2:
            return {"severity": "OK", "message": f"equity={equity:.2f} (accumulating history)", "value": equity}
        baseline = self._equity_history[0][1]
        if baseline <= 0:
            return {"severity": "OK", "message": "equity baseline invalid", "value": equity}
        drop_pct = (baseline - equity) / baseline * 100.0
        if drop_pct >= self.equity_drop_threshold_pct:
            return {
                "severity": "CRITICAL",
                "message": (
                    f"equity dropped {drop_pct:.2f}% from {baseline:.2f} to {equity:.2f} USDT "
                    f"(threshold {self.equity_drop_threshold_pct:.1f}%)"
                ),
                "value": round(drop_pct, 4),
            }
        return {
            "severity": "OK",
            "message": f"equity {equity:.2f} USDT (delta {-drop_pct:+.2f}% from baseline {baseline:.2f})",
            "value": round(drop_pct, 4),
        }

    def _read_current_force_mode(self) -> str:
        """Read force_auto_mode from override file (may differ from daemon's loaded settings)."""
        try:
            raw = self._load_json_safe(self.strategy_override_path)
            return str(raw.get("force_auto_mode", "") or "").strip().lower()
        except Exception:
            return ""

    def _apply_force_auto_mode_normal(self) -> bool:
        try:
            raw = self._load_json_safe(self.strategy_override_path)
            if raw.get("force_auto_mode") == "normal":
                return False  # already set, no-op
            raw["force_auto_mode"] = "normal"
            self._write_json_atomic(self.strategy_override_path, raw)
            return True
        except Exception as exc:
            self.log(f"[WARNING] failed to set force_auto_mode=normal: {exc}")
            return False

    # ------------------------------------------------------------------
    # Disk cleanup
    # ------------------------------------------------------------------

    _PROTECTED_NAMES: frozenset[str] = frozenset(
        {"closed_trades.jsonl", "health_status.json", "policy_state.json"}
    )
    _LOG_NUMBERED_RE = re.compile(r"\.log\.[1-5]$")

    def _is_protected(self, path: Path) -> bool:
        name = path.name
        if name in self._PROTECTED_NAMES:
            return True
        if name.startswith("strategy_override") and name.endswith(".json"):
            return True
        return False

    def _dir_size_bytes(self) -> int:
        total = 0
        try:
            for p in self.output_base.rglob("*"):
                if p.is_file():
                    try:
                        total += p.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def _cleanup_disk(self) -> None:
        """Delete stale log files. Runs once at startup then every 24h."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval_seconds:
            return
        self._last_cleanup = now

        deleted_bytes = 0
        deleted_files: list[str] = []

        # 1. Delete all *.log.old files
        try:
            for p in self.output_base.rglob("*.log.old"):
                if not p.is_file() or self._is_protected(p):
                    continue
                try:
                    size = p.stat().st_size
                    p.unlink()
                    deleted_bytes += size
                    deleted_files.append(f"{p.name}({size // 1024}KB)")
                except OSError:
                    pass
        except OSError:
            pass

        # 2. If total size > 500MB, delete numbered log backups (*.log.1~.5) oldest first
        total_bytes = self._dir_size_bytes()
        if total_bytes > 500 * 1024 * 1024:
            numbered: list[tuple[float, Path]] = []
            try:
                for p in self.output_base.rglob("*"):
                    if not p.is_file() or self._is_protected(p):
                        continue
                    if self._LOG_NUMBERED_RE.search(p.name):
                        try:
                            numbered.append((p.stat().st_mtime, p))
                        except OSError:
                            pass
            except OSError:
                pass
            numbered.sort()  # oldest first
            for _, p in numbered:
                try:
                    size = p.stat().st_size
                    p.unlink()
                    deleted_bytes += size
                    deleted_files.append(f"{p.name}({size // 1024}KB)")
                except OSError:
                    pass

        # Update cached disk usage
        after_bytes = self._dir_size_bytes()
        self._disk_usage_mb = round(after_bytes / (1024 * 1024), 1)

        if deleted_files:
            self.log(
                f"[CLEANUP] deleted {len(deleted_files)} file(s) ({deleted_bytes // 1024}KB): "
                + ", ".join(deleted_files)
                + f"; disk_usage={self._disk_usage_mb}MB"
            )
        else:
            self.log(f"[CLEANUP] no stale files found; disk_usage={self._disk_usage_mb}MB")

    def _write_strategy_health(self, overall: str, checks: dict, auto_actions: list[str]) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "overall_severity": overall,
            "checks": checks,
            "auto_actions": auto_actions,
            "disk_usage_mb": self._disk_usage_mb,
        }
        try:
            self._write_json_atomic(self.strategy_health_path, payload)
        except Exception as exc:
            self.log(f"[WARNING] failed to write health_status.json: {exc}")

    def _run_strategy_health_check(self) -> None:
        # Disk cleanup: runs on first call and every 24h thereafter
        self._cleanup_disk()

        policy_state = self._load_json_safe(self.policy_state_path)
        summary_state = self._load_json_safe(self.summary_path)
        current_force_mode = self._read_current_force_mode()

        auto_actions: list[str] = []
        checks: dict[str, dict] = {}

        checks["adopted_ratio"] = self._check_adopted_ratio()
        checks["tighter_mode"] = self._check_tighter_mode(policy_state, current_force_mode)
        checks["strategy_entries"] = self._check_strategy_entries()
        checks["equity_drop"] = self._check_equity_drop(summary_state)

        # Auto-response: tighter mode detected AND force not already set → apply
        if checks["tighter_mode"]["severity"] in ("WARNING", "CRITICAL"):
            applied = self._apply_force_auto_mode_normal()
            if applied:
                auto_actions.append("set_force_auto_mode_normal")
                self.log(
                    "[WARNING] strategy_health:tighter_mode detected; "
                    "auto-set force_auto_mode=normal in strategy_override.approved.json"
                )

        severities = [c["severity"] for c in checks.values()]
        overall = "CRITICAL" if "CRITICAL" in severities else ("WARNING" if "WARNING" in severities else "OK")

        for name, check in checks.items():
            if check["severity"] != "OK":
                self.log(f"[{check['severity']}] strategy_health:{name} — {check['message']}")

        self._write_strategy_health(overall, checks, auto_actions)

    def step(self) -> None:
        if not self.owns_watchdog_slot():
            current_pid, current_version = self.read_slot(self.watchdog_pid_path)
            self.log(f"watchdog slot lost to pid={current_pid} {current_version or ''}".strip())
            raise SystemExit(0)

        # Strategy health check every 5 min (independent of process liveness check)
        now = time.time()
        if now - self._last_strategy_check >= self.strategy_check_interval_seconds:
            try:
                self._run_strategy_health_check()
            except Exception as exc:
                self.log(f"[WARNING] strategy health check failed: {exc}")
            self._last_strategy_check = now

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
            self.log(
                "supervisor missing but summary still fresh; waiting "
                f"child_alive={child_alive} supervisor_alive={supervisor_alive} "
                f"summary={summary_health.reason} health={health_state.reason}"
            )
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
