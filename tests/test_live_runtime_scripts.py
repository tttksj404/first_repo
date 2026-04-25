from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.daemon_supervisor import _extract_strict_startup_block, _read_stderr_chunk
from scripts.monitor_daemon_health import (
    _bitget_state_from_account_sync,
    _resolve_monitor_end_time,
    _resolve_runtime_dir,
    _select_log_paths,
    _tail,
)
from scripts.start_live_trading import _resolve_python_executable, _rotate_runtime_logs, _wait_for_stack_boot


class LiveRuntimeScriptTests(unittest.TestCase):
    def test_quant_run_live_orders_honors_supervisor_stop_file(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_run_live_orders.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("SUPERVISOR_STOP_FILE", script)
        self.assertIn("mark_stopped_health", script)
        self.assertIn('"stopped"', script)
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
        self.assertIn("live_supervisor_health.json", script)
        self.assertIn("stopped_by_quant_stop", script)
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
        self.assertIn("live_stop_state_applies()", script)
        self.assertIn("health_state_indicates_intentional_stop()", script)
        self.assertIn("describe_stop_requested()", script)
        self.assertIn("persisted stop health detected", script)
        self.assertIn("supervisor_stop_requested|stopped_by_quant_stop", script)
        self.assertIn("STOP_REQUESTED=1", script)
        self.assertIn("runtime intentionally stopped", script)
        self.assertIn('printf \'%s\' "stop sentinel present"', script)
        self.assertIn('printf \'%s\' "persisted stop health present"', script)
        self.assertIn("$(describe_stop_requested); quant_binance process absent as expected", script)
        self.assertIn("$(describe_stop_requested); supervisor pid check skipped", script)
        self.assertIn("$(describe_stop_requested); watchdog check skipped", script)
        self.assertIn("health file reflects intentional stop", script)
        self.assertIn("health stale while runtime is intentionally stopped", script)
        self.assertIn('if [ "$STOP_REQUESTED" = "1" ]; then', script)
        self.assertIn("[STATUS] intentionally stopped — autofix suppressed", script)
        self.assertIn("[SKIP] runtime intentionally stopped — autofix suppressed", script)
        self.assertIn("if live_stop_state_applies && live_stop_requested; then", script)

    def test_quant_health_audit_uses_macos_safe_claude_timeout_guard(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_health_audit.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("macOS에는 timeout 명령 없음", script)
        self.assertIn('( sleep 600 && kill "$CLAUDE_PID" 2>/dev/null ) &', script)
        self.assertNotIn('timeout 600 "$CLAUDE"', script)

    def test_yolo_health_check_skips_exchange_actions_when_stop_sentinel_present(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "yolo_health_check.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("def live_stop_requested()", script)
        self.assertIn("live stop sentinel present — skip automated health fixes", script)
        self.assertLess(script.index("if live_stop_requested():"), script.index("creds = load_exchange_credentials_from_env()"))

    def test_quant_health_audit_supports_paper50_runtime_layout(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_health_audit.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('RUNTIME_INPUT="${1:-${QUANT_HEALTH_AUDIT_RUNTIME:-quant_runtime}}"', script)
        self.assertIn('*) RUNTIME="$REPO/$RUNTIME_INPUT" ;;', script)
        self.assertIn("QUANT_HEALTH_AUDIT_RUNTIME", script)
        self.assertIn("_paper50.out.log", script)
        self.assertIn("PAPER50_MODE=1", script)
        self.assertIn("RUNTIME_BASENAME", script)
        self.assertIn("process table unavailable, but runtime heartbeat log is fresh", script)
        self.assertIn("FORENSICS_ROOT", script)
        self.assertIn('grep "HEARTBEAT" >/dev/null', script)
        self.assertIn("summary_count_keys", script)
        self.assertIn("use_overview_fallback", script)

    def test_quant_health_audit_does_not_apply_live_stop_to_paper50_runtime(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_health_audit.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn('quant_runtime_paper50*|*paper50*', script)
        self.assertIn('live_stop_state_applies() {', script)
        self.assertIn('[ "$PAPER50_MODE" != "1" ]', script)
        self.assertIn("elif live_stop_state_applies && health_state_indicates_intentional_stop; then", script)

    def test_quant_run_paper50_readonly_only_blocks_live_when_requested(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_run_paper50_readonly.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("QUANT_PAPER50_BLOCK_LIVE_AUTO", script)
        self.assertIn("_supervisor_stop", script)
        self.assertLess(script.index("QUANT_PAPER50_BLOCK_LIVE_AUTO"), script.index("_supervisor_stop"))

    def test_quant_run_paper50_readonly_starts_monitor_sidecar(self) -> None:
        script = (Path(__file__).resolve().parents[1] / "scripts" / "quant_run_paper50_readonly.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("scripts/monitor_daemon_health.py", script)
        self.assertIn("_monitor.pid", script)
        self.assertLess(script.index("monitor_daemon_health.py"), script.index("quant_binance.runtime"))

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

    def test_monitor_resolves_fresher_paper50_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            legacy = root / "quant_runtime"
            paper50 = root / "quant_runtime_paper50"
            legacy.mkdir(parents=True, exist_ok=True)
            paper50.mkdir(parents=True, exist_ok=True)
            stale_log = legacy / "_live_auto_trade_live_restart.log"
            fresh_log = paper50 / "_paper50.out.log"
            stale_log.write_text("legacy\n", encoding="utf-8")
            fresh_log.write_text("paper50\n", encoding="utf-8")
            os.utime(stale_log, (1, 1))
            os.utime(fresh_log, None)

            runtime = _resolve_runtime_dir(root)

            self.assertEqual(runtime, paper50)

    def test_monitor_selects_paper50_logs_when_they_are_freshest(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runtime = Path(tempdir) / "quant_runtime_paper50"
            runtime.mkdir(parents=True, exist_ok=True)
            paper_out = runtime / "_paper50.out.log"
            paper_err = runtime / "_paper50.err.log"
            live_out = runtime / "_live_auto_trade_live_restart.log"
            paper_out.write_text("paper50\n", encoding="utf-8")
            paper_err.write_text("", encoding="utf-8")
            live_out.write_text("legacy\n", encoding="utf-8")
            os.utime(live_out, (1, 1))
            os.utime(paper_out, None)

            log_path, err_path = _select_log_paths(runtime)

            self.assertEqual(log_path, paper_out)
            self.assertEqual(err_path, paper_err)

    def test_monitor_defaults_to_indefinite_runtime(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            self.assertIsNone(_resolve_monitor_end_time(now_ts=100.0))

    def test_monitor_respects_explicit_duration_minutes(self) -> None:
        with patch.dict(os.environ, {"MONITOR_MINUTES": "15"}, clear=False):
            self.assertEqual(_resolve_monitor_end_time(now_ts=100.0), 100.0 + 15 * 60)

    def test_monitor_uses_account_sync_fallback_when_direct_probe_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            runtime = Path(tempdir) / "quant_runtime_paper50"
            account_sync = runtime / "forensics" / "account_sync.jsonl"
            overview = runtime / "output" / "paper-live-shell" / "latest" / "overview.json"
            account_sync.parent.mkdir(parents=True, exist_ok=True)
            overview.parent.mkdir(parents=True, exist_ok=True)
            account_sync.write_text(
                (
                    '{"account_snapshot":{"accounts":[{"marginCoin":"USDT","usdtEquity":"57.25"}],'
                    '"unionAvailable":57.25},"timestamp":"2026-04-23T20:08:11.741657+00:00"}\n'
                ),
                encoding="utf-8",
            )
            overview.write_text(
                '{"exchange_live_futures_positions":[{"symbol":"PEPEUSDT","side":"long","qty":12345}]}',
                encoding="utf-8",
            )

            payload = _bitget_state_from_account_sync(
                runtime,
                error_message="Bitget transport error for https://api.bitget.com: DNS resolution failed",
            )

            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertEqual(payload["source"], "account_sync_fallback")
            self.assertEqual(payload["equity_usdt"], 57.25)
            self.assertEqual(payload["positions"], [{"symbol": "PEPEUSDT", "side": "long", "qty": 12345}])
            self.assertEqual(payload["synced_at"], "2026-04-23T20:08:11.741657+00:00")
            self.assertIn("DNS resolution failed", payload["warning"])

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
