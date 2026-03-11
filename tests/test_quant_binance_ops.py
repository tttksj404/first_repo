from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.observability.report import build_runtime_summary, write_runtime_summary
from quant_binance.observability.runtime_state import read_runtime_state, write_runtime_state
from quant_binance.risk.kill_switch import KillSwitch
from quant_binance.service import PaperTradingService
from quant_binance.settings import Settings
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


def make_history() -> FeatureHistoryContext:
    return FeatureHistoryContext(
        returns_1h=(0.01, 0.02, 0.03, 0.04, 0.05),
        returns_4h=(0.02, 0.03, 0.04, 0.05, 0.06),
        quote_volume_5m=(1000, 1100, 1200, 1300, 1400),
        quote_volume_1h=(10000, 10500, 11000, 11500, 12000),
        realized_vol_1h=(0.1, 0.12, 0.14, 0.16, 0.18),
        realized_vol_4h=(0.15, 0.17, 0.19, 0.21, 0.23),
        funding_abs=(0.0001, 0.0002, 0.0003, 0.0004, 0.0005),
        basis_abs=(2.0, 3.0, 4.0, 5.0, 6.0),
        oi_surge=(0.05, 0.1, 0.15, 0.2, 0.25),
    )


def make_primitive() -> PrimitiveInputs:
    return PrimitiveInputs(
        ret_1h=0.05,
        ret_4h=0.06,
        trend_direction=1,
        ema_stack_score=1.0,
        breakout_reference_price=49500.0,
        last_trade_price=50000.0,
        atr_14_1h_price=200.0,
        quote_volume_5m=1600.0,
        quote_volume_1h=13000.0,
        buy_taker_volume=70.0,
        sell_taker_volume=30.0,
        spread_bps=2.0,
        probe_slippage_bps=3.0,
        depth_usd_within_10bps=300000.0,
        order_book_imbalance_std=0.1,
        realized_vol_1h=0.12,
        realized_vol_4h=0.17,
        median_realized_vol_1h_30d=0.12,
        funding_rate=0.0001,
        open_interest=1080000.0,
        open_interest_ema=1000000.0,
        basis_bps=3.0,
        gross_expected_edge_bps=30.0,
    )


class QuantBinanceOpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def setUp(self) -> None:
        self.summary_path = ROOT / "tests" / "tmp_runtime_summary.json"
        self.state_path = ROOT / "tests" / "tmp_runtime_state.json"

    def tearDown(self) -> None:
        for path in (self.summary_path, self.state_path):
            if path.exists():
                path.unlink()

    def test_kill_switch_status_and_clear(self) -> None:
        kill_switch = KillSwitch()
        kill_switch.arm("STALE_DATA")
        self.assertTrue(kill_switch.armed)
        self.assertIn("STALE_DATA", kill_switch.reasons)
        kill_switch.clear()
        self.assertFalse(kill_switch.armed)

    def test_runtime_summary_and_state_write(self) -> None:
        summary = build_runtime_summary(
            decisions=[],
            tested_orders=[{"symbol": "BTCUSDT"}],
            account_snapshot={"accountType": "SPOT"},
            open_orders_snapshot=[],
            closed_trades=[
                {
                    "symbol": "BTCUSDT",
                    "market": "spot",
                    "exit_reason": "PARTIAL_TAKE_PROFIT",
                    "realized_pnl_usd_estimate": 12.5,
                    "realized_return_bps_estimate": 50.0,
                }
            ],
            open_spot_positions=[
                {
                    "symbol": "ETHUSDT",
                    "unrealized_pnl_usd_estimate": 7.5,
                }
            ],
            kill_switch_status={"armed": False, "reasons": []},
        )
        write_runtime_summary(self.summary_path, summary)
        self.assertTrue(self.summary_path.exists())
        self.assertIn("tested_order_count", self.summary_path.read_text(encoding="utf-8"))
        self.assertEqual(summary["realized_pnl_usd_estimate"], 12.5)
        self.assertEqual(summary["unrealized_pnl_usd_estimate"], 7.5)
        self.assertEqual(summary["exit_reason_counts"], {"PARTIAL_TAKE_PROFIT": 1})

        write_runtime_state(self.state_path, {"mode": "paper-live"})
        payload = read_runtime_state(self.state_path)
        self.assertEqual(payload["mode"], "paper-live")
        self.assertIn("updated_at", payload)

    def test_live_runtime_respects_kill_switch(self) -> None:
        now = datetime(2026, 3, 8, 12, 5, 0, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, now - timedelta(seconds=20)),
                last_trade_price=50000.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=3.0,
                last_update_time=now - timedelta(seconds=20),
            )
        )
        kill_switch = KillSwitch()
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(store),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
            kill_switch=kill_switch,
        )
        kill_switch.arm("MANUAL_TEST")
        decision = runtime.on_payload(
            {
                "stream": "btcusdt@kline_5m",
                "data": {
                    "s": "BTCUSDT",
                    "k": {
                        "i": "5m",
                        "t": 1772971200000,
                        "T": 1772971500000,
                        "o": "49900",
                        "h": "50100",
                        "l": "49850",
                        "c": "50050",
                        "v": "12",
                        "q": "600000",
                        "x": True
                    }
                }
            },
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        self.assertIsNone(decision)
        self.assertTrue(kill_switch.armed)


if __name__ == "__main__":
    unittest.main()
