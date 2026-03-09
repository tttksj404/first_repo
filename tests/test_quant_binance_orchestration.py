from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_binance.backtest.oracle import compare_decisions_to_oracle, load_oracle
from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import KlineBar, SpotTrade, SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.runtime import run_paper_live_mode
from quant_binance.service import PaperTradingService
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


def make_history_payload() -> dict[str, tuple[float, ...]]:
    return {
        "returns_1h": (0.01, 0.02, 0.03, 0.04, 0.05),
        "returns_4h": (0.02, 0.03, 0.04, 0.05, 0.06),
        "quote_volume_5m": (1000, 1100, 1200, 1300, 1400),
        "quote_volume_1h": (10000, 10500, 11000, 11500, 12000),
        "realized_vol_1h": (0.1, 0.12, 0.14, 0.16, 0.18),
        "realized_vol_4h": (0.15, 0.17, 0.19, 0.21, 0.23),
        "funding_abs": (0.0001, 0.0002, 0.0003, 0.0004, 0.0005),
        "basis_abs": (2.0, 3.0, 4.0, 5.0, 6.0),
        "oi_surge": (0.05, 0.1, 0.15, 0.2, 0.25),
    }


def make_primitive_payload() -> dict[str, float | int]:
    return {
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
        "gross_expected_edge_bps": 30.0,
    }


class QuantBinanceOrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def setUp(self) -> None:
        self.oracle_path = ROOT / "tests" / "tmp_oracle.json"
        self.paper_live_path = ROOT / "tests" / "tmp_paper_live.json"

    def tearDown(self) -> None:
        for path in (self.oracle_path, self.paper_live_path):
            if path.exists():
                path.unlink()

    def test_market_store_updates_state(self) -> None:
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(49999.0, 1.0, 50001.0, 1.1, now),
                last_trade_price=50000.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=4.0,
                last_update_time=now,
            )
        )
        store.apply_trade(
            SpotTrade(
                symbol="BTCUSDT",
                price=50010.0,
                quantity=0.1,
                event_time=now,
                is_buyer_maker=False,
            )
        )
        store.apply_top_of_book("BTCUSDT", TopOfBook(50009.0, 2.0, 50011.0, 1.0, now))
        store.apply_kline(
            KlineBar(
                symbol="BTCUSDT",
                interval="5m",
                start_time=now,
                close_time=now,
                open_price=49900.0,
                high_price=50100.0,
                low_price=49800.0,
                close_price=50010.0,
                volume=12.0,
                quote_volume=600000.0,
                is_closed=True,
            )
        )
        state = store.get("BTCUSDT")
        assert state is not None
        self.assertEqual(state.last_trade_price, 50010.0)
        self.assertEqual(len(state.order_book_imbalance_samples), 1)
        self.assertEqual(len(state.klines["5m"]), 1)

    def test_oracle_comparison_matches_segments(self) -> None:
        self.oracle_path.write_text(
            json.dumps(
                {
                    "segments": [
                        {
                            "start": "2026-03-08T12:05:00+00:00",
                            "end": "2026-03-08T12:10:00+00:00",
                            "expected_mode": "futures",
                            "expected_side": "long",
                            "note": "trend",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        oracle = load_oracle(self.oracle_path)
        service = PaperTradingService(self.settings, router=ExecutionRouter())
        now = datetime(2026, 3, 8, 12, 5, 0, tzinfo=timezone.utc)
        decision = service.run_cycle(
            state=SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, now),
                last_trade_price=50000.0,
                funding_rate=0.0002,
                open_interest=1200000.0,
                basis_bps=5.5,
                last_update_time=now,
            ),
            primitive_inputs=PrimitiveInputs(**make_primitive_payload()),
            history=FeatureHistoryContext(**make_history_payload()),
            decision_time=now,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        report = compare_decisions_to_oracle([decision], oracle)
        self.assertEqual(report.matched_segments, 1)
        self.assertEqual(report.segment_accuracy, 1.0)

    def test_run_paper_live_mode_from_fixture(self) -> None:
        now = "2026-03-08T12:05:00+00:00"
        self.paper_live_path.write_text(
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
                                "funding_rate": 0.0002,
                                "open_interest": 1200000.0,
                                "basis_bps": 5.5,
                                "last_update_time": now,
                            },
                            "primitive_inputs": make_primitive_payload(),
                            "history": make_history_payload(),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        summary = run_paper_live_mode(
            config_path=CONFIG_PATH,
            fixture_path=self.paper_live_path,
            equity_usd=10000.0,
            capacity_usd=5000.0,
        )
        self.assertEqual(summary["cycle_count"], 1)
        self.assertEqual(summary["decision_count"], 1)
        self.assertEqual(summary["modes"], ["futures"])


if __name__ == "__main__":
    unittest.main()
