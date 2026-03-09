from __future__ import annotations

import unittest

from quant_binance.remote import REMOTE_COMMANDS, resolve_remote_command


class QuantBinanceRemoteTests(unittest.TestCase):
    def test_resolve_remote_command(self) -> None:
        command = resolve_remote_command("start-live")
        self.assertEqual(command.action, "start-live")
        self.assertIn("quant_run_live_orders.sh", command.script)

    def test_known_remote_commands_exist(self) -> None:
        for name in ("start", "start-live", "status", "report", "stop", "smoke", "extract"):
            self.assertIn(name, REMOTE_COMMANDS)


if __name__ == "__main__":
    unittest.main()
