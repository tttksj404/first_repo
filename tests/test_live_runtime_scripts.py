from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.daemon_supervisor import _extract_strict_startup_block, _read_stderr_chunk
from scripts.monitor_daemon_health import _tail
from scripts.start_live_trading import _resolve_python_executable, _rotate_runtime_logs, _wait_for_stack_boot


class LiveRuntimeScriptTests(unittest.TestCase):
    def test_quant_run_live_orders_honors_supervisor_stop_file(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_run_live_orders.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("SUPERVISOR_STOP_FILE", script)
        self.assertIn("refusing to start", script)
        self.assertIn("not restarting", script)

    def test_quant_run_live_orders_ignores_previous_summary_during_startup_grace(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_run_live_orders.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("CHILD_STARTED_AT_EPOCH", script)
        self.assertIn("updated_at.timestamp() < child_started_epoch", script)
        self.assertIn("previous_summary_state_startup_grace", script)
        self.assertLess(script.index("previous_summary_state_startup_grace"), script.index('runtime_status == "startup_failed"'))

    def test_quant_run_live_orders_backs_off_startup_failures(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_run_live_orders.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("QUANT_LIVE_STARTUP_FAILURE_BACKOFF_SECONDS", script)
        self.assertIn('[ "$HEALTH_REASON" = "startup_failed" ]', script)
        self.assertIn("startup_failed; backing off", script)

    def test_quant_stop_stops_supervisor_watchdog_and_writes_stop_files(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_stop.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("_supervisor_stop", script)
        self.assertIn("_safety_guardian_stop", script)
        self.assertIn("live_supervisor_watchdog.pid", script)
        self.assertIn("scripts/quant_run_live_orders.sh", script)

    def test_quant_health_audit_requires_explicit_restart_permission(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_health_audit.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("QUANT_HEALTH_AUDIT_ALLOW_RESTART", script)
        self.assertIn("clear_live_stop_files()", script)
        self.assertIn("$REPO/scripts/_supervisor_stop", script)
        self.assertIn("$REPO/scripts/_safety_guardian_stop", script)
        restart_block = script.split('if [ "$YOLO_EXIT" -eq 1 ]; then', maxsplit=1)[1]
        self.assertIn('if [ "$ALLOW_RESTART" = "1" ]; then', restart_block)
        self.assertIn("재시작은 QUANT_HEALTH_AUDIT_ALLOW_RESTART=1 없어서 차단", restart_block)
        allowed_block = restart_block.split('if [ "$ALLOW_RESTART" = "1" ]; then', maxsplit=1)[1]
        self.assertLess(allowed_block.index("clear_live_stop_files"), allowed_block.index("nohup bash"))

    def test_quant_health_audit_classifies_stop_sentinel_as_stopped(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_health_audit.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("live_stop_requested()", script)
        self.assertIn("STOP_REQUESTED=1", script)
        self.assertIn("runtime intentionally stopped", script)
        self.assertIn("quant_binance process absent as expected", script)
        self.assertIn("health stale while runtime is intentionally stopped", script)

    def test_quant_health_audit_supports_paper50_runtime_layout(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_health_audit.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("QUANT_HEALTH_AUDIT_RUNTIME", script)
        self.assertIn("_paper50.out.log", script)
        self.assertIn("PAPER50_MODE=1", script)
        self.assertIn("process table unavailable, but runtime heartbeat log is fresh", script)
        self.assertIn("FORENSICS_ROOT", script)
        self.assertIn('grep "HEARTBEAT" >/dev/null', script)

    def test_quant_run_paper50_readonly_only_blocks_live_when_requested(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_run_paper50_readonly.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("QUANT_PAPER50_BLOCK_LIVE_AUTO", script)
        self.assertIn("_supervisor_stop", script)
        self.assertLess(script.index("QUANT_PAPER50_BLOCK_LIVE_AUTO"), script.index("_supervisor_stop"))

    def test_quant_health_audit_does_not_count_heartbeat_numbers_as_429s(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_health_audit.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("HTTP[[:space:]/_-]*429", script)
        self.assertNotIn('"429\\|rate.limit"', script)

    def test_quant_run_live_orders_logs_watchdog_start_failure_without_aborting(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_run_live_orders.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("watchdog_start_status=$?", script)
        self.assertIn("watchdog start request failed", script)
        self.assertIn("requested watchdog start pid=", script)

    def test_tail_strips_nul_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "runtime.err.log"
            path.write_bytes(b"alpha\x00\x00beta\nline2\x00\n")

            lines = _tail(path, 10)

            self.assertEqual(lines, ["alphabeta", "line2"])

    def test_rotate_runtime_logs_archives_previous_restart_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / "quant_runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            stdout_log = runtime / "_live_auto_trade_live_restart.log"
            stderr_log = runtime / "_live_auto_trade_live_restart.err.log"
            stdout_log.write_text("stdout-old\n", encoding="utf-8")
            stderr_log.write_text("stderr-old\n", encoding="utf-8")

            _rotate_runtime_logs(root)

            archive_dir = runtime / "archive"
            archived = sorted(archive_dir.iterdir())
            self.assertEqual(len(archived), 2)
            self.assertEqual(stdout_log.read_text(encoding="utf-8"), "")
            self.assertEqual(stderr_log.read_text(encoding="utf-8"), "")
            self.assertTrue(any(item.name.startswith("_live_auto_trade_live_restart.log.") for item in archived))
            self.assertTrue(any(item.name.startswith("_live_auto_trade_live_restart.err.log.") for item in archived))

    def test_read_stderr_chunk_reads_only_new_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "runtime.err.log"
            path.write_text("old-line\n", encoding="utf-8")
            start_offset = path.stat().st_size
            with path.open("a", encoding="utf-8") as handle:
                handle.write("new-line\n")

            chunk = _read_stderr_chunk(stderr_path=path, start_offset=start_offset)

            self.assertEqual(chunk.replace("\r\n", "\n"), "new-line\n")

    def test_extract_strict_startup_block_returns_last_matching_line(self) -> None:
        stderr_chunk = "\n".join(
            [
                "noise",
                "STRICT_STARTUP_POSITION_BLOCK: first hit",
                "more noise",
                "STRICT_STARTUP_POSITION_BLOCK: second hit",
            ]
        )

        line = _extract_strict_startup_block(stderr_chunk)

        self.assertEqual(line, "STRICT_STARTUP_POSITION_BLOCK: second hit")

    def test_resolve_python_executable_prefers_repo_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            python_path = root / ".venv" / "Scripts" / "python.exe"
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("", encoding="utf-8")

            resolved = _resolve_python_executable(root)

            self.assertEqual(resolved, str(python_path))

    def test_wait_for_stack_boot_succeeds_when_components_and_raw_daemon_are_running(self) -> None:
        root = Path(tempfile.gettempdir())
        components = [{"name": "supervisor"}, {"name": "monitor"}]
        with patch(
            "scripts.start_live_trading._detect_existing",
            side_effect=[
                [("supervisor", "1", "cmd")],
                [("supervisor", "1", "cmd"), ("monitor", "2", "cmd"), ("raw-daemon", "3", "cmd")],
            ],
        ):
            ok, details = _wait_for_stack_boot(root, components, timeout_seconds=2)

        self.assertTrue(ok)
        self.assertEqual(details, "")

    def test_wait_for_stack_boot_surfaces_strict_startup_block(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runtime = root / "quant_runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "_supervisor.log").write_text(
                "STRICT_STARTUP_POSITION_BLOCK: found live startup position(s)\n",
                encoding="utf-8",
            )
            components = [{"name": "supervisor"}, {"name": "monitor"}]
            with patch("scripts.start_live_trading._detect_existing", return_value=[]):
                ok, details = _wait_for_stack_boot(root, components, timeout_seconds=1)

        self.assertFalse(ok)
        self.assertIn("strict startup block detected", details)
        self.assertIn("STRICT_STARTUP_POSITION_BLOCK", details)


if __name__ == "__main__":
    unittest.main()
