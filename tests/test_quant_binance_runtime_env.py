from __future__ import annotations

import os
import unittest
from pathlib import Path

from quant_binance.env import load_binance_credentials_from_env, runtime_readiness
from quant_binance.execution.binance_rest import BinanceCredentials
from quant_binance.runtime import run_paper_live_test_order_mode


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class FakeBinanceRestClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def test_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
        self.calls.append((market, order_params))
        return {"status": "ok"}


class QuantBinanceRuntimeEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_path = ROOT / "tests" / "tmp_paper_live_order_test.json"
        now = "2026-03-08T12:05:00+00:00"
        self.fixture_path.write_text(
            """
{
  "cycles": [
    {
      "decision_time": "%s",
      "symbol": "BTCUSDT",
      "state": {
        "top_of_book": {
          "bid_price": 49999.5,
          "bid_qty": 1.0,
          "ask_price": 50000.5,
          "ask_qty": 1.2,
          "updated_at": "%s"
        },
        "last_trade_price": 50000.0,
        "funding_rate": 0.0001,
        "open_interest": 1080000.0,
        "basis_bps": 3.0,
        "last_update_time": "%s"
      },
      "primitive_inputs": {
        "ret_1h": 0.05,
        "ret_4h": 0.06,
        "trend_direction": 1,
        "ema_stack_score": 1.0,
        "breakout_reference_price": 49500.0,
        "last_trade_price": 50000.0,
        "atr_14_1h_price": 200.0,
        "quote_volume_5m": 1600.0,
        "quote_volume_1h": 13000.0,
        "buy_taker_volume": 70.0,
        "sell_taker_volume": 30.0,
        "spread_bps": 2.0,
        "probe_slippage_bps": 3.0,
        "depth_usd_within_10bps": 300000.0,
        "order_book_imbalance_std": 0.1,
        "realized_vol_1h": 0.12,
        "realized_vol_4h": 0.17,
        "median_realized_vol_1h_30d": 0.12,
        "funding_rate": 0.0001,
        "open_interest": 1080000.0,
        "open_interest_ema": 1000000.0,
        "basis_bps": 3.0,
        "gross_expected_edge_bps": 30.0
      },
      "history": {
        "returns_1h": [0.01, 0.02, 0.03, 0.04, 0.05],
        "returns_4h": [0.02, 0.03, 0.04, 0.05, 0.06],
        "quote_volume_5m": [1000, 1100, 1200, 1300, 1400],
        "quote_volume_1h": [10000, 10500, 11000, 11500, 12000],
        "realized_vol_1h": [0.1, 0.12, 0.14, 0.16, 0.18],
        "realized_vol_4h": [0.15, 0.17, 0.19, 0.21, 0.23],
        "funding_abs": [0.0001, 0.0002, 0.0003, 0.0004, 0.0005],
        "basis_abs": [2.0, 3.0, 4.0, 5.0, 6.0],
        "oi_surge": [0.05, 0.1, 0.15, 0.2, 0.25]
      }
    }
  ]
}
"""
            % (now, now, now),
            encoding="utf-8",
        )
        self._old_api_key = os.environ.get("BINANCE_API_KEY")
        self._old_api_secret = os.environ.get("BINANCE_API_SECRET")

    def tearDown(self) -> None:
        if self.fixture_path.exists():
            self.fixture_path.unlink()
        if self._old_api_key is None:
            os.environ.pop("BINANCE_API_KEY", None)
        else:
            os.environ["BINANCE_API_KEY"] = self._old_api_key
        if self._old_api_secret is None:
            os.environ.pop("BINANCE_API_SECRET", None)
        else:
            os.environ["BINANCE_API_SECRET"] = self._old_api_secret

    def test_runtime_readiness_reflects_env(self) -> None:
        os.environ["BINANCE_API_KEY"] = "key"
        os.environ["BINANCE_API_SECRET"] = "secret"
        readiness = runtime_readiness()
        self.assertTrue(readiness.is_ready)

    def test_load_credentials_from_env(self) -> None:
        os.environ["BINANCE_API_KEY"] = "key"
        os.environ["BINANCE_API_SECRET"] = "secret"
        creds = load_binance_credentials_from_env()
        self.assertEqual(creds.api_key, "key")
        self.assertEqual(creds.api_secret, "secret")

    def test_paper_live_test_order_mode_uses_test_adapter(self) -> None:
        fake_client = FakeBinanceRestClient()
        summary = run_paper_live_test_order_mode(
            config_path=CONFIG_PATH,
            fixture_path=self.fixture_path,
            equity_usd=10000.0,
            capacity_usd=5000.0,
            client=fake_client,  # type: ignore[arg-type]
        )
        self.assertEqual(summary["cycle_count"], 1)
        self.assertEqual(summary["tested_order_count"], 1)
        self.assertEqual(len(fake_client.calls), 1)


if __name__ == "__main__":
    unittest.main()
