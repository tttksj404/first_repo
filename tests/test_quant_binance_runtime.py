from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from quant_binance.backtest.fixtures import load_snapshot_fixture
from quant_binance.execution.binance_rest import BinanceCredentials, BinanceRestClient, sign_query_string
from quant_binance.runtime import build_arg_parser, run_paper_live_shell_mode, run_replay_mode


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class QuantBinanceRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture_path = ROOT / "tests" / "tmp_replay_fixture.json"
        self.paper_live_fixture_path = ROOT / "tests" / "tmp_paper_live_shell.json"
        self.output_path = ROOT / "tests" / "tmp_paper_live_shell_summary.json"
        self.fixture_path.write_text(
            json.dumps(
                {
                    "snapshots": [
                        {
                            "snapshot_id": "snap-1",
                            "config_version": "2026-03-08.v1",
                            "snapshot_schema_version": "1.0.0",
                            "symbol": "BTCUSDT",
                            "decision_time": "2026-03-08T12:05:00+00:00",
                            "last_trade_price": 50000.0,
                            "best_bid": 49999.5,
                            "best_ask": 50000.5,
                            "funding_rate": 0.0001,
                            "open_interest": 1000000.0,
                            "basis_bps": 4.5,
                            "data_freshness_ms": 250,
                            "feature_values": {
                                "ret_rank_1h": 0.8,
                                "ret_rank_4h": 0.78,
                                "breakout_norm": 0.82,
                                "ema_stack_score": 1.0,
                                "vol_z_5m_norm": 0.7,
                                "vol_z_1h_norm": 0.72,
                                "taker_imbalance_norm": 0.69,
                                "spread_bps_norm": 0.2,
                                "probe_slippage_bps_norm": 0.25,
                                "depth_10bps_norm": 0.86,
                                "book_stability_norm": 0.9,
                                "realized_vol_1h_norm": 0.3,
                                "realized_vol_4h_norm": 0.28,
                                "vol_shock_norm": 0.35,
                                "funding_abs_percentile": 0.14,
                                "oi_surge_percentile": 0.1,
                                "basis_stretch_percentile": 0.18,
                                "regime_alignment": 1.0,
                                "trend_direction": 1,
                                "trend_strength": 0.82,
                                "volume_confirmation": 0.74,
                                "liquidity_score": 0.86,
                                "volatility_penalty": 0.28,
                                "overheat_penalty": 0.14,
                                "predictability_score": 0.0,
                                "gross_expected_edge_bps": 24.0,
                                "net_expected_edge_bps": 0.0,
                                "estimated_round_trip_cost_bps": 10.0
                            }
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        now = "2026-03-08T12:05:00+00:00"
        self.paper_live_fixture_path.write_text(
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
        if self.paper_live_fixture_path.exists():
            self.paper_live_fixture_path.unlink()
        if self.output_path.exists():
            self.output_path.unlink()
        state_path = self.output_path.with_suffix(".state.json")
        if state_path.exists():
            state_path.unlink()

    def test_sign_query_string_stable(self) -> None:
        query, signature = sign_query_string("secret", {"symbol": "BTCUSDT", "timestamp": 1})
        self.assertEqual(query, "symbol=BTCUSDT&timestamp=1")
        self.assertEqual(len(signature), 64)

    def test_build_signed_request_contains_signature(self) -> None:
        client = BinanceRestClient(
            credentials=BinanceCredentials(api_key="key", api_secret="secret")
        )
        request = client.build_signed_request(
            market="spot",
            path="/api/v3/order/test",
            method="POST",
            params={"symbol": "BTCUSDT", "side": "BUY"},
        )
        parsed = urlparse(request.full_url)
        params = parse_qs(parsed.query)
        self.assertIn("signature", params)
        self.assertEqual(request.headers["X-mbx-apikey"], "key")

    def test_fixture_loader_reads_snapshot(self) -> None:
        snapshots = load_snapshot_fixture(self.fixture_path)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].symbol, "BTCUSDT")

    def test_runtime_replay_mode_returns_summary(self) -> None:
        summary = run_replay_mode(
            config_path=CONFIG_PATH,
            fixture_path=self.fixture_path,
            equity_usd=10000.0,
            capacity_usd=5000.0,
        )
        self.assertEqual(summary["decision_count"], 1)
        self.assertEqual(summary["order_count"], 1)

    def test_runtime_paper_live_shell_mode_returns_summary(self) -> None:
        summary = run_paper_live_shell_mode(
            config_path=CONFIG_PATH,
            fixture_path=self.paper_live_fixture_path,
            equity_usd=10000.0,
            capacity_usd=5000.0,
            output_path=self.output_path,
            max_retries=2,
        )
        self.assertEqual(summary["cycle_count"], 1)
        self.assertEqual(summary["decision_count"], 1)
        self.assertTrue(self.output_path.exists())
        self.assertTrue(self.output_path.with_suffix(".state.json").exists())

    def test_arg_parser_requires_mode(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--mode", "replay", "--fixture", "x.json"])
        self.assertEqual(args.mode, "replay")


if __name__ == "__main__":
    unittest.main()
