from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.daemon_supervisor import _extract_strict_startup_block, _read_stderr_chunk
from scripts.monitor_daemon_health import _tail
from scripts.start_live_trading import _resolve_python_executable, _rotate_runtime_logs, _wait_for_stack_boot


class LiveRuntimeScriptTests(unittest.TestCase):
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
