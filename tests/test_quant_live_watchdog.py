from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import textwrap
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHDOG_SCRIPT = ROOT / "scripts" / "quant_live_watchdog.sh"


class QuantLiveWatchdogTests(unittest.TestCase):
    def _watchdog_env(self, supervisor_stub: Path) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "QUANT_RUN_SUPERVISOR_SCRIPT": str(supervisor_stub),
                "QUANT_SUPERVISOR_WATCHDOG_INTERVAL_SECONDS": "1",
                "QUANT_SUPERVISOR_WATCHDOG_STALE_SECONDS": "1",
                "QUANT_SUPERVISOR_WATCHDOG_RESTART_COOLDOWN_SECONDS": "1",
                "QUANT_LIVE_STARTUP_GRACE_SECONDS": "0",
                "QUANT_SUPERVISOR_STOP_FILE": str(supervisor_stub.with_name("nonexistent_supervisor_stop")),
            }
        )
        return env

    def _launch_watchdog(self, output_dir: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            ["/bin/sh", str(WATCHDOG_SCRIPT), str(output_dir)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    @unittest.skipIf(os.name == "nt", "watchdog shell integration requires POSIX /bin/sh")
    def test_watchdog_replaces_legacy_pidfile_owner_before_restarting_supervisor(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir) / "runtime"
            output_dir.mkdir(parents=True, exist_ok=True)
            legacy_proc = subprocess.Popen(
                ["/bin/sh", "-c", "trap '' TERM; while :; do sleep 1; done"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            restart_marker = Path(tempdir) / "restart.marker"
            supervisor_stub = Path(tempdir) / "supervisor_stub.sh"
            supervisor_stub.write_text(
                textwrap.dedent(
                    f"""\
                    #!/bin/sh
                    set -eu
                    printf 'started\\n' >> "{restart_marker}"
                    exit 0
                    """
                ),
                encoding="utf-8",
            )
            supervisor_stub.chmod(0o755)

            pidfile = output_dir / "live_supervisor_watchdog.pid"
            pidfile.write_text(f"{legacy_proc.pid}\n", encoding="utf-8")

            watchdog_proc = self._launch_watchdog(output_dir, self._watchdog_env(supervisor_stub))
            try:
                deadline = time.time() + 10
                while time.time() < deadline and not restart_marker.exists():
                    time.sleep(0.2)
                self.assertTrue(restart_marker.exists(), "watchdog did not restart the supervisor stub")

                deadline = time.time() + 5
                while time.time() < deadline and legacy_proc.poll() is None:
                    time.sleep(0.1)
                self.assertIsNotNone(legacy_proc.poll(), "legacy watchdog process was not replaced")

                pid_fields = pidfile.read_text(encoding="utf-8").strip().split()
                self.assertGreaterEqual(len(pid_fields), 2)
                self.assertEqual(pid_fields[0], str(watchdog_proc.pid))
                self.assertTrue(pid_fields[1].startswith("v3:"))
            finally:
                if watchdog_proc.poll() is None:
                    os.killpg(watchdog_proc.pid, signal.SIGTERM)
                    watchdog_proc.wait(timeout=5)
                if legacy_proc.poll() is None:
                    os.killpg(legacy_proc.pid, signal.SIGKILL)
                    legacy_proc.wait(timeout=5)

    def test_watchdog_treats_fresh_startup_failure_summary_as_unhealthy(self) -> None:
        from scripts.quant_live_watchdog import QuantLiveWatchdog

        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir) / "runtime"
            latest_dir = output_dir / "output" / "paper-live-shell" / "latest"
            latest_dir.mkdir(parents=True, exist_ok=True)
            (latest_dir / "summary.state.json").write_text(
                textwrap.dedent(
                    f"""\
                    {{
                      "status": "startup_failed",
                      "updated_at": "{datetime.now(timezone.utc).isoformat()}",
                      "error": "Bitget DNS resolution failed"
                    }}
                    """
                ),
                encoding="utf-8",
            )

            watchdog = QuantLiveWatchdog(output_base=output_dir)
            health = watchdog.summary_health()

        self.assertFalse(health.fresh)
        self.assertEqual(health.reason, "startup_failed")

    def test_watchdog_classifies_startup_transport_failure(self) -> None:
        from scripts.quant_live_watchdog import QuantLiveWatchdog

        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir) / "runtime"
            latest_dir = output_dir / "output" / "paper-live-shell" / "latest"
            latest_dir.mkdir(parents=True, exist_ok=True)
            (latest_dir / "summary.state.json").write_text(
                textwrap.dedent(
                    f"""\
                    {{
                      "status": "startup_failed",
                      "updated_at": "{datetime.now(timezone.utc).isoformat()}",
                      "error": "Bitget transport error: DNS resolution failed: nodename nor servname provided"
                    }}
                    """
                ),
                encoding="utf-8",
            )

            watchdog = QuantLiveWatchdog(output_base=output_dir)
            self.assertTrue(watchdog.startup_failure_is_transport())

    @unittest.skipIf(os.name == "nt", "watchdog shell integration requires POSIX /bin/sh")
    def test_watchdog_skips_restart_when_summary_is_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            output_dir = Path(tempdir) / "runtime"
            latest_dir = output_dir / "output" / "paper-live-shell" / "latest"
            latest_dir.mkdir(parents=True, exist_ok=True)

            summary_state = latest_dir / "summary.state.json"
            summary_state.write_text(
                textwrap.dedent(
                    f"""\
                    {{
                      "updated_at": "{datetime.now(timezone.utc).isoformat()}",
                      "heartbeat_count": 10,
                      "decision_count": 4
                    }}
                    """
                ),
                encoding="utf-8",
            )

            restart_marker = Path(tempdir) / "restart.marker"
            supervisor_stub = Path(tempdir) / "supervisor_stub.sh"
            supervisor_stub.write_text(
                textwrap.dedent(
                    f"""\
                    #!/bin/sh
                    set -eu
                    printf 'started\\n' >> "{restart_marker}"
                    exit 0
                    """
                ),
                encoding="utf-8",
            )
            supervisor_stub.chmod(0o755)

            env = self._watchdog_env(supervisor_stub)
            env["QUANT_SUPERVISOR_WATCHDOG_STALE_SECONDS"] = "30"
            watchdog_proc = self._launch_watchdog(output_dir, env)
            try:
                time.sleep(2.5)
                self.assertFalse(restart_marker.exists(), "watchdog restarted the supervisor despite a fresh summary")

                log_path = output_dir / "live_supervisor.log"
                deadline = time.time() + 5
                while time.time() < deadline and not log_path.exists():
                    time.sleep(0.1)
                self.assertTrue(log_path.exists(), "watchdog did not create a supervisor log")
                self.assertIn(
                    "supervisor missing but summary still fresh; waiting",
                    log_path.read_text(encoding="utf-8"),
                )
            finally:
                if watchdog_proc.poll() is None:
                    os.killpg(watchdog_proc.pid, signal.SIGTERM)
                    watchdog_proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
