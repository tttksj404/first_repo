from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.daemon_supervisor import _extract_strict_startup_block, _read_stderr_chunk
from scripts.monitor_daemon_health import _tail
from scripts.start_live_trading import _rotate_runtime_logs


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


if __name__ == "__main__":
    unittest.main()
