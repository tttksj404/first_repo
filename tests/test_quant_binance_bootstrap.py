from __future__ import annotations

import unittest
from pathlib import Path

from quant_binance.bootstrap import initialize_workspace


ROOT = Path(__file__).resolve().parents[1]


class QuantBinanceBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base_dir = ROOT / "tests" / "tmp_workspace"

    def tearDown(self) -> None:
        if self.base_dir.exists():
            for path in sorted(self.base_dir.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                else:
                    path.rmdir()

    def test_initialize_workspace_creates_expected_directories(self) -> None:
        layout = initialize_workspace(self.base_dir)
        self.assertTrue(layout.output_root.exists())
        self.assertTrue((layout.output_root / "replay").exists())
        self.assertTrue((layout.output_root / "paper-live-shell").exists())
        self.assertTrue(layout.artifact_root.exists())
        self.assertTrue(layout.oracle_root.exists())
        self.assertTrue(layout.manifest_root.exists())


if __name__ == "__main__":
    unittest.main()
