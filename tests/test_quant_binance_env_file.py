from __future__ import annotations

import os
import unittest
from pathlib import Path

from quant_binance.env import load_binance_credentials_from_env, runtime_readiness


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


class QuantBinanceEnvFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_env_text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else None
        self.old_api_key = os.environ.pop("BINANCE_API_KEY", None)
        self.old_api_secret = os.environ.pop("BINANCE_API_SECRET", None)

    def tearDown(self) -> None:
        if self.original_env_text is None:
            if ENV_PATH.exists():
                ENV_PATH.unlink()
        else:
            ENV_PATH.write_text(self.original_env_text, encoding="utf-8")
        if self.old_api_key is not None:
            os.environ["BINANCE_API_KEY"] = self.old_api_key
        if self.old_api_secret is not None:
            os.environ["BINANCE_API_SECRET"] = self.old_api_secret

    def test_runtime_readiness_reads_root_env_file(self) -> None:
        appended = "\nBINANCE_API_KEY=file_key\nBINANCE_API_SECRET=file_secret\n"
        current = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
        ENV_PATH.write_text(current + appended, encoding="utf-8")
        readiness = runtime_readiness()
        self.assertTrue(readiness.is_ready)
        creds = load_binance_credentials_from_env()
        self.assertEqual(creds.api_key, "file_key")
        self.assertEqual(creds.api_secret, "file_secret")


if __name__ == "__main__":
    unittest.main()
