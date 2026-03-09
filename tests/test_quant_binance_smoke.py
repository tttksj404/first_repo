from __future__ import annotations

import json
import unittest
from pathlib import Path

from quant_binance.paths import prepare_run_paths
from quant_binance.smoke import run_smoke


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class FakeBinanceRestClient:
    def test_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        return {"status": "ok", "market": market, "order_params": order_params}

    def get_account(self, *, market):  # type: ignore[no-untyped-def]
        return {"market": market, "balance": 1000}

    def get_open_orders(self, *, market, symbol=None):  # type: ignore[no-untyped-def]
        return {"market": market, "orders": []}


class QuantBinanceSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_path = ROOT / "tests" / "tmp_smoke_paper_live.json"
        self.output_base = ROOT / "tests" / "tmp_output"
        now = "2026-03-08T12:05:00+00:00"
        self.fixture_path.write_text(
            json.dumps(
                {
                    "cycles": [
                        {
                            "decision_time": now,
                            "symbol": "BTCUSDT",
                            "state": {
                                "top_of_book": {
                                    "bid_price": 49999.5,
                                    "bid_qty": 1.0,
                                    "ask_price": 50000.5,
                                    "ask_qty": 1.2,
                                    "updated_at": now,
                                },
                                "last_trade_price": 50000.0,
                                "funding_rate": 0.0001,
                                "open_interest": 1080000.0,
                                "basis_bps": 3.0,
                                "last_update_time": now,
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
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        if self.fixture_path.exists():
            self.fixture_path.unlink()
        if self.output_base.exists():
            for path in sorted(self.output_base.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                else:
                    path.rmdir()

    def test_prepare_run_paths_creates_expected_layout(self) -> None:
        paths = prepare_run_paths(base_dir=self.output_base, mode="paper-live-shell", run_id="test-run")
        self.assertTrue(paths.root.exists())
        self.assertEqual(paths.summary_path.name, "summary.json")
        self.assertEqual(paths.state_path.name, "summary.state.json")

    def test_run_smoke_writes_outputs(self) -> None:
        result = run_smoke(
            mode="paper-live-shell",
            config_path=CONFIG_PATH,
            fixture_path=self.fixture_path,
            output_base_dir=self.output_base,
            run_id="smoke-run",
        )
        paths = result["paths"]
        assert hasattr(paths, "summary_path")
        self.assertTrue(paths.summary_path.exists())
        self.assertTrue(paths.state_path.exists())

    def test_run_smoke_test_order_mode(self) -> None:
        result = run_smoke(
            mode="paper-live-test-order",
            config_path=CONFIG_PATH,
            fixture_path=self.fixture_path,
            output_base_dir=self.output_base,
            client=FakeBinanceRestClient(),
            run_id="test-order-run",
        )
        summary = result["summary"]
        self.assertEqual(summary["tested_order_count"], 1)


if __name__ == "__main__":
    unittest.main()
