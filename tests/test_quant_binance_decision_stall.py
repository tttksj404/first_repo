from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.self_healing import RuntimeSelfHealing
from quant_binance.service import PaperTradingService
from quant_binance.session import BackoffPolicy, LivePaperSession, LivePaperShell
from quant_binance.settings import Settings


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


class FakeWsClient:
    def __init__(self, payloads):
        self.payloads = payloads

    async def run(self, handler):
        for payload in self.payloads:
            await handler(payload)


class HeartbeatOnlyWsClient:
    def __init__(self, payloads, *, delay_seconds=0.2):
        self.payloads = payloads
        self.delay_seconds = delay_seconds

    async def run(self, handler):
        index = 0
        while True:
            await handler(self.payloads[index % len(self.payloads)])
            index += 1
            await asyncio.sleep(self.delay_seconds)


class HeartbeatOnlyThenHealthyFactory:
    def __init__(self, *, heartbeat_payloads, decision_payloads):
        self.heartbeat_payloads = heartbeat_payloads
        self.decision_payloads = decision_payloads
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls == 1:
            return HeartbeatOnlyWsClient(self.heartbeat_payloads)
        return FakeWsClient(self.decision_payloads)


class QuantBinanceDecisionStallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def _build_session(self) -> LivePaperSession:
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, now),
                last_trade_price=50000.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=3.0,
                last_update_time=now,
            )
        )
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(store),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        return LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )

    def test_live_paper_shell_self_heals_when_heartbeats_continue_without_decisions(self) -> None:
        session = self._build_session()
        session.self_healing = RuntimeSelfHealing(
            stall_timeout_seconds=1,
            max_stall_restarts_per_window=2,
            stall_restart_window_seconds=600,
        )
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        session.run_bootstrap_cycle(
            state=state,
            primitive_inputs=make_primitive(),
            history=make_history(),
            decision_time=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
        )
        summary_path = ROOT / "tests" / "tmp_shell_decision_stall_summary.json"
        state_path = ROOT / "tests" / "tmp_shell_decision_stall_state.json"
        try:
            shell = LivePaperShell(
                ws_client_factory=HeartbeatOnlyThenHealthyFactory(
                    heartbeat_payloads=[
                        {
                            "stream": "btcusdt@bookTicker",
                            "data": {
                                "s": "BTCUSDT",
                                "b": "50009",
                                "B": "2",
                                "a": "50011",
                                "A": "1",
                                "E": 1772971560000,
                            },
                        }
                    ],
                    decision_payloads=[
                        {
                            "stream": "btcusdt@kline_5m",
                            "data": {
                                "s": "BTCUSDT",
                                "k": {
                                    "i": "5m",
                                    "t": 1772971500000,
                                    "T": 1772971799999,
                                    "o": "50000",
                                    "h": "50100",
                                    "l": "49950",
                                    "c": "50080",
                                    "v": "18",
                                    "q": "900000",
                                    "x": True,
                                },
                            },
                        }
                    ],
                ),
                session=session,
                backoff_policy=BackoffPolicy(
                    initial_delay_seconds=0.0,
                    max_delay_seconds=0.0,
                    multiplier=1.0,
                    max_attempts=2,
                ),
                summary_path=summary_path,
                state_path=state_path,
            )
            summary = asyncio.run(shell.run())
            assert summary is not None
            self.assertEqual(summary["decision_count"], 2)
            self.assertEqual(len(session.decisions), 2)
            self.assertTrue(
                any(
                    event["category"] == "daemon_stalled"
                    and event["action"] == "restart_websocket"
                    and event["details"].get("stall_kind") == "decision_progress"
                    for event in summary["self_healing"]["recent_events"]
                )
            )
        finally:
            if summary_path.exists():
                summary_path.unlink()
            if state_path.exists():
                state_path.unlink()

    def test_future_bootstrap_decision_does_not_trigger_early_stall_restart(self) -> None:
        session = self._build_session()
        session.self_healing = RuntimeSelfHealing(
            stall_timeout_seconds=360,
            max_stall_restarts_per_window=2,
            stall_restart_window_seconds=600,
        )
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        bootstrap_decision_time = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        session.run_bootstrap_cycle(
            state=state,
            primitive_inputs=make_primitive(),
            history=make_history(),
            decision_time=bootstrap_decision_time,
        )

        self.assertEqual(session.last_decision_timestamp, bootstrap_decision_time)
        self.assertFalse(
            session.self_healing.detect_stall(
                now=datetime(2026, 3, 8, 12, 11, tzinfo=timezone.utc),
            )
        )


if __name__ == "__main__":
    unittest.main()
