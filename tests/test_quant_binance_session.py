from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.bitget_rest import BitgetRestClient
from quant_binance.execution.order_test_adapter import DecisionOrderTestAdapter
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.models import DecisionIntent
from quant_binance.observability.log_store import JsonlLogStore
from quant_binance.service import PaperTradingService
from quant_binance.session import AsyncLivePaperRunner, BackoffPolicy, LivePaperSession, LivePaperShell
from quant_binance.self_healing import KNOWN_CATEGORY_MISSING_MARKET_STATE, RuntimeSelfHealing
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


def make_decision(
    *,
    timestamp: datetime,
    symbol: str = "BTCUSDT",
    final_mode: str = "futures",
    side: str = "long",
    predictability_score: float = 82.0,
    liquidity_score: float = 0.8,
    gross_expected_edge_bps: float = 28.0,
    net_expected_edge_bps: float = 18.0,
    estimated_round_trip_cost_bps: float = 10.0,
    order_intent_notional_usd: float = 1000.0,
    stop_distance_bps: float = 500.0,
) -> DecisionIntent:
    return DecisionIntent(
        decision_id=f"decision-{timestamp.isoformat()}-{final_mode}-{side}",
        decision_hash=f"hash-{timestamp.isoformat()}-{final_mode}-{side}",
        snapshot_id=f"snapshot-{timestamp.isoformat()}",
        config_version="2026-03-10.v1",
        timestamp=timestamp,
        symbol=symbol,
        candidate_mode="futures",
        final_mode=final_mode,
        side=side,
        trend_direction=1 if side == "long" else -1,
        trend_strength=0.85,
        volume_confirmation=0.78,
        liquidity_score=liquidity_score,
        volatility_penalty=0.2,
        overheat_penalty=0.1,
        predictability_score=predictability_score,
        gross_expected_edge_bps=gross_expected_edge_bps,
        net_expected_edge_bps=net_expected_edge_bps,
        estimated_round_trip_cost_bps=estimated_round_trip_cost_bps,
        order_intent_notional_usd=order_intent_notional_usd,
        stop_distance_bps=stop_distance_bps,
    )


class FakeRestClient:
    def __init__(self) -> None:
        self.account_calls = 0
        self.open_order_calls = 0
        self.cancelled_orders: list[tuple[str, str, str]] = []

    def get_account(self, *, market: str) -> dict[str, object]:
        self.account_calls += 1
        return {"market": market, "balance": 1000}

    def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, object]:
        self.open_order_calls += 1
        return {"market": market, "orders": []}

    def get_positions(self) -> dict[str, object]:
        return {"positions": []}

    def cancel_order(self, *, market: str, symbol: str, order_id: str) -> dict[str, object]:
        self.cancelled_orders.append((market, symbol, order_id))
        return {"status": "SUCCESS", "orderId": order_id}


class FakeOrderTestClient:
    def test_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        return {"status": "ok", "market": market, "order_params": order_params}


class FakeWsClient:
    def __init__(self, payloads):
        self.payloads = payloads

    async def run(self, handler):
        for payload in self.payloads:
            await handler(payload)


class FlakyWsFactory:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls == 1:
            return FailingWsClient()
        return FakeWsClient(self.payloads)


class FailingWsClient:
    async def run(self, handler):
        raise RuntimeError("temporary websocket failure")


class StalledWsClient:
    async def run(self, handler):
        await asyncio.Event().wait()


class StalledThenHealthyFactory:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls == 1:
            return StalledWsClient()
        return FakeWsClient(self.payloads)


class QuantBinanceSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def _build_session(self, *, settings: Settings | None = None) -> LivePaperSession:
        active_settings = settings or self.settings
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
            paper_service=PaperTradingService(active_settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=active_settings.decision_engine.decision_interval_minutes,
        )
        return LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=FakeRestClient(),
            order_tester=DecisionOrderTestAdapter(FakeOrderTestClient()),  # type: ignore[arg-type]
            sync_interval_seconds=1,
        )

    def _focus_settings(self, *, futures_top_n: int) -> Settings:
        return replace(
            self.settings,
            portfolio_focus=replace(
                self.settings.portfolio_focus,
                enabled=True,
                futures_top_n=futures_top_n,
                min_score_advantage_to_replace=5.0,
                min_net_edge_advantage_bps=2.0,
                min_incremental_pnl_usd=1.0,
            ),
        )

    def _seed_weak_futures_position(
        self,
        session: LivePaperSession,
        *,
        symbol: str,
        entry_time: datetime,
        entry_price: float = 100.0,
        current_price: float = 90.0,
        quantity: float = 40.0,
        entry_predictability_score: float = 82.0,
        latest_predictability_score: float = 73.0,
        entry_net_expected_edge_bps: float = 16.0,
        latest_net_expected_edge_bps: float = 7.0,
        entry_estimated_round_trip_cost_bps: float = 6.0,
        latest_estimated_round_trip_cost_bps: float = 6.0,
        entry_planned_leverage: int = 2,
    ) -> None:
        session.paper_positions[symbol] = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol=symbol,
            market="futures",
            side="long",
            entry_time=entry_time,
            entry_price=entry_price,
            current_price=current_price,
            quantity_opened=quantity,
            quantity_remaining=quantity,
            stop_distance_bps=500.0,
            active_stop_price=95.0,
            best_price=max(entry_price, current_price),
            worst_price=min(entry_price, current_price, 88.0),
            entry_predictability_score=entry_predictability_score,
            entry_liquidity_score=0.8,
            entry_net_expected_edge_bps=entry_net_expected_edge_bps,
            entry_estimated_round_trip_cost_bps=entry_estimated_round_trip_cost_bps,
            entry_planned_leverage=entry_planned_leverage,
            latest_predictability_score=latest_predictability_score,
            latest_liquidity_score=0.7,
            latest_net_expected_edge_bps=latest_net_expected_edge_bps,
            latest_estimated_round_trip_cost_bps=latest_estimated_round_trip_cost_bps,
            latest_decision_time=entry_time + timedelta(minutes=5),
        )

    def _seed_strategy_owned_live_position(
        self,
        session: LivePaperSession,
        *,
        symbol: str,
        side: str = "long",
        entry_time: datetime | None = None,
        entry_price: float = 100.0,
        current_price: float | None = None,
        quantity: float = 1.0,
        leverage: int = 1,
    ) -> None:
        opened_at = entry_time or datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        mark_price = entry_price if current_price is None else current_price
        session.paper_positions[symbol] = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol=symbol,
            market="futures",
            side=side,
            entry_time=opened_at,
            entry_price=entry_price,
            current_price=mark_price,
            quantity_opened=quantity,
            quantity_remaining=quantity,
            stop_distance_bps=0.0,
            active_stop_price=entry_price,
            best_price=max(entry_price, mark_price),
            worst_price=min(entry_price, mark_price),
            entry_predictability_score=70.0,
            entry_liquidity_score=0.75,
            entry_net_expected_edge_bps=8.0,
            entry_estimated_round_trip_cost_bps=4.0,
            entry_planned_leverage=max(leverage, 1),
            latest_predictability_score=70.0,
            latest_liquidity_score=0.75,
            latest_net_expected_edge_bps=8.0,
            latest_estimated_round_trip_cost_bps=4.0,
            latest_decision_time=opened_at,
            exchange_synced=True,
            origin="strategy",
        )

    def _record_closed_loss_trade(
        self,
        session: LivePaperSession,
        *,
        symbol: str,
        side: str,
        entry_time: datetime,
        exit_time: datetime,
        realized_loss_usd: float,
        quantity_opened: float = 1.0,
        quantity_closed: float = 1.0,
    ) -> None:
        loss_size = abs(realized_loss_usd)
        entry_price = 100.0
        exit_price = entry_price + loss_size if side == "short" else entry_price - loss_size
        position = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol=symbol,
            market="futures",
            side=side,
            entry_time=entry_time,
            entry_price=entry_price,
            current_price=exit_price,
            quantity_opened=quantity_opened,
            quantity_remaining=quantity_opened,
            stop_distance_bps=500.0,
            active_stop_price=95.0 if side == "long" else 105.0,
            best_price=max(entry_price, exit_price),
            worst_price=min(entry_price, exit_price),
            entry_predictability_score=70.0,
            entry_liquidity_score=0.7,
            latest_predictability_score=55.0,
            latest_liquidity_score=0.6,
            latest_net_expected_edge_bps=2.0,
            latest_decision_time=exit_time,
            entry_net_expected_edge_bps=8.0,
            entry_estimated_round_trip_cost_bps=6.0,
            entry_planned_leverage=2,
        )
        session._record_closed_trade(
            position=position,
            exit_price=exit_price,
            quantity_closed=quantity_closed,
            exit_time=exit_time,
            exit_reason="STOP_LOSS",
        )

    def test_session_syncs_and_flushes(self) -> None:
        session = self._build_session()
        session.observe_only_symbols = ["SIGNUSDT"]
        now = datetime(2026, 3, 8, 12, 5, 0, tzinfo=timezone.utc)
        payload = {
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
                    "x": True,
                },
            },
        }
        decision = session.process_payload(payload, now=now)
        self.assertIsNotNone(decision)
        summary_path = ROOT / "tests" / "tmp_session_summary.json"
        state_path = ROOT / "tests" / "tmp_session_state.json"
        try:
            summary = session.flush(summary_path=summary_path, state_path=state_path)
            self.assertEqual(summary["decision_count"], 1)
            self.assertEqual(summary["tested_order_count"], 1)
            self.assertEqual(summary["observe_only_symbols"], ["SIGNUSDT"])
            self.assertTrue(summary_path.exists())
            self.assertTrue(state_path.exists())
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state_payload["live_decision_loop"]["closed_decision_kline_count"], 1)
            self.assertEqual(state_payload["live_decision_loop"]["emitted_decision_count"], 1)
        finally:
            if summary_path.exists():
                summary_path.unlink()
            if state_path.exists():
                state_path.unlink()

    def test_session_continues_emitting_after_bootstrap(self) -> None:
        session = self._build_session()
        bootstrap_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        before = datetime.now(tz=timezone.utc)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        session.run_bootstrap_cycle(
            state=state,
            primitive_inputs=make_primitive(),
            history=make_history(),
            decision_time=bootstrap_time,
        )
        decision = session.process_payload(
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
            },
            now=datetime(2026, 3, 8, 12, 10, 1, tzinfo=timezone.utc),
        )
        self.assertIsNotNone(decision)
        self.assertEqual(len(session.decisions), 2)
        self.assertEqual(session.decisions[-1].timestamp.isoformat(), "2026-03-08T12:10:00+00:00")
        self.assertEqual(session.last_decision_timestamp.isoformat(), "2026-03-08T12:10:00+00:00")
        assert session.last_decision_emitted_at is not None
        self.assertGreaterEqual(session.last_decision_emitted_at, before)
        assert session.self_healing.last_decision_at is not None
        self.assertGreaterEqual(session.self_healing.last_decision_at, before)
        self.assertEqual(session.runtime.loop_stats.closed_decision_kline_count, 1)
        self.assertEqual(session.runtime.loop_stats.emitted_decision_count, 1)

    def test_bootstrap_cycle_does_not_open_paper_position_or_submit_order(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        bootstrap_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)

        session.run_bootstrap_cycle(
            state=state,
            primitive_inputs=make_primitive(),
            history=make_history(),
            decision_time=bootstrap_time,
        )

        self.assertEqual(len(session.decisions), 1)
        self.assertEqual(session.paper_positions, {})
        self.assertEqual(session.tested_orders, [])

    def test_session_runs_scheduled_decision_boundary_without_closed_kline(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        session.run_bootstrap_cycle(
            state=state,
            primitive_inputs=make_primitive(),
            history=make_history(),
            decision_time=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
        )

        decision = session.process_payload(
            {
                "stream": "btcusdt@trade",
                "data": {
                    "s": "BTCUSDT",
                    "p": "50080",
                    "q": "0.2",
                    "E": int(datetime(2026, 3, 8, 12, 10, 0, tzinfo=timezone.utc).timestamp() * 1000),
                    "m": False,
                },
            },
            now=datetime(2026, 3, 8, 12, 10, 0, tzinfo=timezone.utc),
        )

        self.assertIsNone(decision)
        self.assertEqual(len(session.decisions), 2)
        self.assertEqual(session.decisions[-1].symbol, "BTCUSDT")
        self.assertEqual(session.decisions[-1].timestamp.isoformat(), "2026-03-08T12:10:00+00:00")

    def test_session_skips_missing_market_state_payload_without_crashing(self) -> None:
        session = self._build_session()
        skip_time = datetime(2026, 3, 8, 12, 6, tzinfo=timezone.utc)
        decision_time = datetime(2026, 3, 8, 12, 10, 1, tzinfo=timezone.utc)
        summary_path = ROOT / "tests" / "tmp_session_missing_market_state_summary.json"
        state_path = ROOT / "tests" / "tmp_session_missing_market_state_state.json"

        skipped = session.process_payload(
            {
                "stream": "ethusdt@trade",
                "data": {"s": "ETHUSDT", "p": "2100", "q": "0.2", "E": 1772971560000, "m": False},
            },
            now=skip_time,
        )
        decision = session.process_payload(
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
            },
            now=decision_time,
        )

        self.assertIsNone(skipped)
        self.assertIsNotNone(decision)
        self.assertEqual(len(session.decisions), 1)
        self.assertEqual(session.self_healing.recent_events[-1].category, KNOWN_CATEGORY_MISSING_MARKET_STATE)
        try:
            summary = session.flush(summary_path=summary_path, state_path=state_path)
            self.assertEqual(
                summary["self_healing"]["issue_counts"][KNOWN_CATEGORY_MISSING_MARKET_STATE],
                1,
            )
            self.assertEqual(
                summary["self_healing"]["recent_events"][-1]["category"],
                KNOWN_CATEGORY_MISSING_MARKET_STATE,
            )
        finally:
            if summary_path.exists():
                summary_path.unlink()
            if state_path.exists():
                state_path.unlink()

    def test_session_takes_partial_profit_then_closes_remainder_at_breakeven(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        starting_capacity = session.remaining_portfolio_capacity_usd
        session._record_decision(
            decision=make_decision(timestamp=entry_time),
            state=state,
            timestamp=entry_time,
        )

        self.assertEqual(len(session.paper_positions), 1)
        self.assertEqual(len(session.tested_orders), 1)
        self.assertEqual(session.remaining_portfolio_capacity_usd, starting_capacity - 1000.0)

        take_profit_time = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state.last_trade_price = 108.0
        session._record_decision(
            decision=make_decision(timestamp=take_profit_time, order_intent_notional_usd=1200.0),
            state=state,
            timestamp=take_profit_time,
        )

        self.assertEqual(len(session.paper_positions), 1)
        self.assertEqual(len(session.closed_trades), 1)
        self.assertEqual(session.closed_trades[0]["exit_reason"], "PARTIAL_TAKE_PROFIT")
        self.assertEqual(len(session.tested_orders), 1)
        self.assertEqual(session.remaining_portfolio_capacity_usd, starting_capacity - 460.0)

        breakeven_time = datetime(2026, 3, 8, 12, 15, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=breakeven_time, order_intent_notional_usd=900.0),
            state=state,
            timestamp=breakeven_time,
        )

        self.assertEqual(len(session.paper_positions), 0)
        self.assertEqual(len(session.closed_trades), 2)
        self.assertEqual(session.closed_trades[-1]["exit_reason"], "BREAKEVEN_STOP")
        self.assertEqual(session.remaining_portfolio_capacity_usd, starting_capacity)

        summary_path = ROOT / "tests" / "tmp_session_profit_summary.json"
        state_path = ROOT / "tests" / "tmp_session_profit_state.json"
        try:
            summary = session.flush(summary_path=summary_path, state_path=state_path)
            self.assertEqual(summary["closed_trades"][0]["exit_reason"], "PARTIAL_TAKE_PROFIT")
            self.assertEqual(summary["closed_trades"][-1]["exit_reason"], "BREAKEVEN_STOP")
            self.assertEqual(summary["open_futures_positions"], [])
            self.assertEqual(summary["realized_pnl_usd_estimate"], 40.0)
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state_payload["closed_trade_count"], 2)
            self.assertEqual(state_payload["open_futures_position_count"], 0)
        finally:
            if summary_path.exists():
                summary_path.unlink()
            if state_path.exists():
                state_path.unlink()

    def test_session_flush_writes_exchange_and_paper_futures_position_mismatch_state(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=entry_time),
            state=state,
            timestamp=entry_time,
        )
        session.live_positions_snapshot = [
            {"symbol": "BTCUSDT", "holdSide": "long", "total": "0.02", "available": "0.02"},
            {"symbol": "ETHUSDT", "holdSide": "short", "total": "0.05", "available": "0.05"},
        ]

        summary_path = ROOT / "tests" / "tmp_session_mismatch_summary.json"
        state_path = ROOT / "tests" / "tmp_session_mismatch_state.json"
        try:
            summary = session.flush(summary_path=summary_path, state_path=state_path)
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))

            self.assertEqual(summary["paper_open_futures_position_count"], 1)
            self.assertEqual(summary["exchange_live_futures_position_count"], 2)
            self.assertTrue(summary["futures_position_mismatch"])
            self.assertEqual(
                summary["futures_position_mismatch_details"],
                {"missing_in_paper": ["ETHUSDT"], "missing_on_exchange": []},
            )
            self.assertEqual(state_payload["paper_open_futures_position_count"], 1)
            self.assertEqual(state_payload["exchange_live_futures_position_count"], 2)
            self.assertTrue(state_payload["futures_position_mismatch"])
            self.assertEqual(
                state_payload["futures_position_mismatch_details"],
                {"missing_in_paper": ["ETHUSDT"], "missing_on_exchange": []},
            )
        finally:
            if summary_path.exists():
                summary_path.unlink()
            if state_path.exists():
                state_path.unlink()

    def test_sync_account_reconciles_persistent_live_futures_position_missing_in_paper(self) -> None:
        class PositionRestClient(FakeRestClient):
            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "ETHUSDT",
                            "holdSide": "short",
                            "total": "0.50",
                            "available": "0.50",
                            "openPriceAvg": "2100.0",
                            "markPrice": "2110.0",
                            "leverage": "5",
                            "cTime": "1772971200000",
                        }
                    ]
                }

        session = self._build_session()
        session.rest_client = PositionRestClient()
        starting_capacity = session.remaining_portfolio_capacity_usd

        session.sync_account()
        self.assertNotIn("ETHUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_in_paper_counts, {"ETHUSDT": 1})
        self.assertEqual(session.remaining_portfolio_capacity_usd, starting_capacity)

        session.sync_account()
        self.assertIn("ETHUSDT", session.paper_positions)
        position = session.paper_positions["ETHUSDT"]
        self.assertEqual(position.side, "short")
        self.assertEqual(position.entry_time.isoformat(), "2026-03-08T12:00:00+00:00")
        self.assertEqual(position.entry_price, 2100.0)
        self.assertEqual(position.current_price, 2110.0)
        self.assertEqual(position.entry_planned_leverage, 5)
        self.assertEqual(position.stop_distance_bps, 0.0)
        self.assertEqual(position.active_stop_price, 2100.0)
        self.assertEqual(position.entry_predictability_score, 0.0)
        self.assertEqual(position.latest_net_expected_edge_bps, 0.0)
        self.assertEqual(position.origin, "adopted")
        self.assertEqual(position.adoption_source, "manual_exchange_external")
        self.assertIsNotNone(position.adopted_at)
        self.assertIsNotNone(position.adoption_grace_until)
        self.assertTrue(position.adoption_grace_active(now=position.adopted_at))
        self.assertAlmostEqual(session.remaining_portfolio_capacity_usd, starting_capacity - 1055.0)
        self.assertEqual(session.futures_missing_in_paper_counts, {})

        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            state_path = Path(tmpdir) / "summary.state.json"
            summary = session.flush(summary_path=summary_path, state_path=state_path)
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(summary["adopted_futures_position_count"], 1)
        self.assertEqual(summary["adopted_futures_positions"][0]["symbol"], "ETHUSDT")
        self.assertEqual(summary["pending_external_futures_position_count"], 0)
        self.assertEqual(state_payload["adopted_futures_position_count"], 1)
        self.assertEqual(state_payload["adopted_futures_positions"][0]["origin"], "adopted")

        session.sync_account()
        self.assertAlmostEqual(session.remaining_portfolio_capacity_usd, starting_capacity - 1055.0)
        self.assertEqual(session.paper_positions["ETHUSDT"].quantity_remaining, 0.5)

    def test_sync_account_does_not_close_external_live_position_before_or_during_adoption(self) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.place_attempts = 0

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "ETHUSDT",
                            "holdSide": "short",
                            "total": "0.50",
                            "available": "0.50",
                            "openPriceAvg": "2100.0",
                            "markPrice": "2110.0",
                            "unrealizedPL": "-5.0",
                            "marginSize": "40.0",
                            "leverage": "5",
                            "cTime": "1772971200000",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.place_attempts += 1
                raise AssertionError("external/manual live position should not be force-closed during adoption")

        session = self._build_session()
        rest_client = PositionRestClient()
        session.rest_client = rest_client

        session.sync_account()
        self.assertEqual(rest_client.place_attempts, 0)
        self.assertNotIn("ETHUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_in_paper_counts, {"ETHUSDT": 1})

        session.sync_account()
        self.assertEqual(rest_client.place_attempts, 0)
        self.assertIn("ETHUSDT", session.paper_positions)
        self.assertEqual(session.paper_positions["ETHUSDT"].origin, "adopted")

    def test_record_decision_does_not_take_strategy_ownership_of_adopted_manual_position(self) -> None:
        class PositionRestClient(FakeRestClient):
            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "ETHUSDT",
                            "holdSide": "short",
                            "total": "0.50",
                            "available": "0.50",
                            "openPriceAvg": "2100.0",
                            "markPrice": "2110.0",
                            "leverage": "5",
                            "cTime": "1772971200000",
                        }
                    ]
                }

        session = self._build_session()
        session.rest_client = PositionRestClient()
        session.sync_account()
        session.sync_account()

        eth_now = datetime(2026, 3, 8, 12, 6, tzinfo=timezone.utc)
        session.runtime.dispatcher.store.put(
            SymbolMarketState(
                symbol="ETHUSDT",
                top_of_book=TopOfBook(2109.5, 1.0, 2110.5, 1.2, eth_now),
                last_trade_price=2110.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=3.0,
                last_update_time=eth_now,
            )
        )
        eth_state = session.runtime.dispatcher.store.get("ETHUSDT")
        assert eth_state is not None

        session._record_decision(
            decision=make_decision(timestamp=eth_now, symbol="ETHUSDT", side="short"),
            state=eth_state,
            timestamp=eth_now,
        )

        self.assertEqual(session.tested_orders, [])
        self.assertEqual(session.paper_positions["ETHUSDT"].origin, "adopted")
        self.assertEqual(session.paper_positions["ETHUSDT"].latest_predictability_score, 0.0)

    def test_sync_account_keeps_reconciled_futures_position_through_brief_exchange_snapshot_gap(self) -> None:
        class FlappingPositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self._snapshots = [
                    [
                        {
                            "symbol": "ETHUSDT",
                            "holdSide": "short",
                            "total": "0.50",
                            "available": "0.50",
                            "openPriceAvg": "2100.0",
                            "markPrice": "2110.0",
                            "leverage": "5",
                            "cTime": "1772971200000",
                        }
                    ],
                    [
                        {
                            "symbol": "ETHUSDT",
                            "holdSide": "short",
                            "total": "0.50",
                            "available": "0.50",
                            "openPriceAvg": "2100.0",
                            "markPrice": "2110.0",
                            "leverage": "5",
                            "cTime": "1772971200000",
                        }
                    ],
                    [],
                    [],
                    [
                        {
                            "symbol": "ETHUSDT",
                            "holdSide": "short",
                            "total": "0.50",
                            "available": "0.50",
                            "openPriceAvg": "2100.0",
                            "markPrice": "2110.0",
                            "leverage": "5",
                            "cTime": "1772971200000",
                        }
                    ],
                ]
                self._index = 0

            def get_positions(self) -> dict[str, object]:
                if self._index < len(self._snapshots):
                    positions = self._snapshots[self._index]
                    self._index += 1
                else:
                    positions = self._snapshots[-1]
                return {"positions": positions}

        session = self._build_session()
        session.rest_client = FlappingPositionRestClient()

        session.sync_account()
        self.assertNotIn("ETHUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_in_paper_counts, {"ETHUSDT": 1})

        session.sync_account()
        self.assertIn("ETHUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_in_paper_counts, {})

        session.sync_account()
        self.assertIn("ETHUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_on_exchange_counts, {"ETHUSDT": 1})

        session.sync_account()
        self.assertIn("ETHUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_on_exchange_counts, {"ETHUSDT": 2})

        session.sync_account()
        self.assertIn("ETHUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_on_exchange_counts, {})

    @patch("quant_binance.session.send_telegram_message")
    def test_sync_account_cleans_up_persistent_paper_futures_position_missing_on_exchange(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, object]:
                return {"market": market, "orders": {"entrustedList": [{"symbol": "BTCUSDT", "orderId": "open-1"}]}}

            def get_positions(self) -> dict[str, object]:
                return {"positions": []}

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=now),
            state=state,
            timestamp=now,
        )
        self.assertIn("BTCUSDT", session.paper_positions)

        session.sync_account()
        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_on_exchange_counts, {"BTCUSDT": 1})

        session.sync_account()
        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_on_exchange_counts, {"BTCUSDT": 2})

        session.sync_account()
        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_on_exchange_counts, {"BTCUSDT": 3})

        session.sync_account()
        self.assertNotIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_on_exchange_counts, {})
        self.assertEqual(session.closed_trades[-1]["exit_reason"], "MANUAL_CLOSE_SYNCED")
        self.assertEqual(session.rest_client.cancelled_orders, [("futures", "BTCUSDT", "open-1")])
        self.assertIn("BTCUSDT", session.manual_symbol_cooldowns)
        self.assertTrue(any("MANUAL_CLOSE_SYNCED" in call.args[0] for call in mock_send.call_args_list))

    @patch("quant_binance.session.send_telegram_message")
    def test_sync_account_uses_higher_missing_on_exchange_threshold_for_major_symbol(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def get_positions(self) -> dict[str, object]:
                return {"positions": []}

        mock_send.return_value = {"ok": True}
        settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_missing_on_exchange_threshold=8,
            ),
        )
        session = self._build_session(settings=settings)
        session.rest_client = PositionRestClient()
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=now),
            state=state,
            timestamp=now,
        )

        for _ in range(7):
            session.sync_account()
            self.assertIn("BTCUSDT", session.paper_positions)

        session.sync_account()

        self.assertNotIn("BTCUSDT", session.paper_positions)

    @patch("quant_binance.session.send_telegram_message")
    def test_sync_account_releases_capacity_and_slot_on_confirmed_manual_close(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self._balances = [5.0, 605.0]
                self._balance_index = 0
                self._positions = [
                    [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "total": "10.0",
                            "available": "10.0",
                            "openPriceAvg": "100.0",
                            "markPrice": "100.0",
                            "leverage": "2",
                        }
                    ],
                    [],
                ]
                self._position_index = 0

            def get_account(self, *, market: str) -> dict[str, object]:
                balance = self._balances[min(self._balance_index, len(self._balances) - 1)]
                self._balance_index += 1
                return {
                    "market": market,
                    "balance": 1000.0,
                    "availableBalance": balance,
                    "executionAvailableBalance": balance,
                }

            def get_positions(self) -> dict[str, object]:
                positions = self._positions[min(self._position_index, len(self._positions) - 1)]
                self._position_index += 1
                return {"positions": positions}

        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=self._focus_settings(futures_top_n=1))
        session.rest_client = PositionRestClient()
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=now),
            state=state,
            timestamp=now,
        )

        self.assertEqual(session.remaining_portfolio_capacity_usd, 4000.0)
        session.sync_account()
        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.remaining_portfolio_capacity_usd, 4000.0)

        session.sync_account()

        self.assertNotIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_on_exchange_counts, {})
        self.assertEqual(session.closed_trades[-1]["exit_reason"], "MANUAL_CLOSE_SYNCED")
        self.assertEqual(session.remaining_portfolio_capacity_usd, 5000.0)

        eth_now = now + timedelta(minutes=1)
        session.runtime.dispatcher.store.put(
            SymbolMarketState(
                symbol="ETHUSDT",
                top_of_book=TopOfBook(199.5, 1.0, 200.5, 1.2, eth_now),
                last_trade_price=200.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=3.0,
                last_update_time=eth_now,
            )
        )
        eth_state = session.runtime.dispatcher.store.get("ETHUSDT")
        assert eth_state is not None

        managed = session._maybe_reallocate_futures_entry(
            decision=make_decision(timestamp=eth_now, symbol="ETHUSDT"),
            state=eth_state,
            timestamp=eth_now,
        )

        self.assertEqual(managed.final_mode, "futures")
        self.assertNotIn("MAX_CONCURRENT_FUTURES", managed.rejection_reasons)

    @patch("quant_binance.session.send_telegram_message")
    def test_sync_account_requires_balance_release_before_fast_manual_close_cleanup(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self._balances = [5.0, 5.0]
                self._balance_index = 0
                self._positions = [
                    [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "total": "10.0",
                            "available": "10.0",
                            "openPriceAvg": "100.0",
                            "markPrice": "100.0",
                            "leverage": "2",
                        }
                    ],
                    [],
                ]
                self._position_index = 0

            def get_account(self, *, market: str) -> dict[str, object]:
                balance = self._balances[min(self._balance_index, len(self._balances) - 1)]
                self._balance_index += 1
                return {
                    "market": market,
                    "balance": 1000.0,
                    "availableBalance": balance,
                    "executionAvailableBalance": balance,
                }

            def get_positions(self) -> dict[str, object]:
                positions = self._positions[min(self._position_index, len(self._positions) - 1)]
                self._position_index += 1
                return {"positions": positions}

        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=self._focus_settings(futures_top_n=1))
        session.rest_client = PositionRestClient()
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=now),
            state=state,
            timestamp=now,
        )

        session.sync_account()
        session.sync_account()

        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_on_exchange_counts, {"BTCUSDT": 1})
        self.assertEqual(session.remaining_portfolio_capacity_usd, 4000.0)
        self.assertEqual(mock_send.call_count, 0)

    @patch("quant_binance.session.send_telegram_message")
    def test_sync_account_is_noop_when_paper_and_exchange_futures_positions_are_aligned(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "total": "10.0",
                            "available": "10.0",
                            "openPriceAvg": "100.0",
                            "markPrice": "100.0",
                        }
                    ]
                }

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_trade_price = 100.0
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        session._record_decision(
            decision=make_decision(timestamp=now),
            state=state,
            timestamp=now,
        )
        starting_capacity = session.remaining_portfolio_capacity_usd
        starting_trade_count = len(session.closed_trades)

        session.sync_account()
        session.sync_account()

        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(len(session.closed_trades), starting_trade_count)
        self.assertEqual(session.futures_missing_in_paper_counts, {})
        self.assertEqual(session.futures_missing_on_exchange_counts, {})
        self.assertEqual(session.remaining_portfolio_capacity_usd, starting_capacity)

    def test_cap_live_order_decision_respects_existing_futures_notional_headroom(self) -> None:
        session = self._build_session()
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 150.0,
            "futures_available_balance_usd": 150.0,
            "futures_requirements": [
                {
                    "symbol": "DOGEUSDT",
                    "min_notional_usd": 5.0,
                    "min_quantity": 1.0,
                }
            ],
        }
        session.paper_positions["BTCUSDT"] = self._seed_weak_futures_position(
            session,
            symbol="BTCUSDT",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            entry_price=100.0,
            current_price=100.0,
            quantity=40.0,
        )
        session.paper_positions["ETHUSDT"] = self._seed_weak_futures_position(
            session,
            symbol="ETHUSDT",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            entry_price=100.0,
            current_price=100.0,
            quantity=40.0,
        )
        decision = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="DOGEUSDT",
            order_intent_notional_usd=3900.0,
        )

        capped = session._cap_live_order_decision(decision, reference_price=100.0)

        self.assertEqual(capped.final_mode, "futures")
        self.assertLessEqual(capped.order_intent_notional_usd, 2000.0)

    def test_cap_live_order_decision_blocks_too_small_meaningful_notional(self) -> None:
        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                min_meaningful_futures_notional_usd=40.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 100.0,
            "futures_available_balance_usd": 100.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        decision = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            order_intent_notional_usd=20.0,
            net_expected_edge_bps=40.0,
        )
        capped = session._cap_live_order_decision(decision, reference_price=100.0)
        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("MIN_MEANINGFUL_NOTIONAL", capped.rejection_reasons)

    def test_cap_live_order_decision_blocks_expected_profit_too_small(self) -> None:
        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                min_meaningful_futures_notional_usd=0.0,
                min_expected_profit_usd_per_trade=6.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 100.0,
            "futures_available_balance_usd": 100.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        decision = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            order_intent_notional_usd=100.0,
            net_expected_edge_bps=100.0,
        )
        capped = session._cap_live_order_decision(decision, reference_price=100.0)
        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("EXPECTED_PROFIT_TOO_SMALL", capped.rejection_reasons)

    def test_cap_live_order_decision_raises_major_strong_entry_to_minimum_notional(self) -> None:
        settings = replace(
            self.settings,
            mode_thresholds=replace(
                self.settings.mode_thresholds,
                futures_score_min=60.0,
            ),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                strong_score_buffer=0.5,
                strong_trend_strength_min=0.6,
                strong_volume_confirmation_min=0.5,
                strong_liquidity_min=0.42,
                strong_volatility_penalty_max=0.55,
                strong_overheat_penalty_max=0.45,
                strong_edge_to_cost_multiple_min=1.0,
                major_min_meaningful_notional_usd=120.0,
                major_strong_min_entry_notional_usd=180.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 250.0,
            "futures_available_balance_usd": 250.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        decision = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            predictability_score=70.0,
            gross_expected_edge_bps=18.0,
            estimated_round_trip_cost_bps=10.0,
            net_expected_edge_bps=8.0,
            order_intent_notional_usd=120.0,
        )

        capped = session._cap_live_order_decision(decision, reference_price=100.0)

        self.assertEqual(capped.final_mode, "futures")
        self.assertEqual(capped.order_intent_notional_usd, 180.0)

    def test_cap_live_order_decision_blocks_major_strong_entry_when_minimum_notional_cannot_be_met(self) -> None:
        settings = replace(
            self.settings,
            mode_thresholds=replace(
                self.settings.mode_thresholds,
                futures_score_min=60.0,
            ),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                strong_score_buffer=0.5,
                strong_trend_strength_min=0.6,
                strong_volume_confirmation_min=0.5,
                strong_liquidity_min=0.42,
                strong_volatility_penalty_max=0.55,
                strong_overheat_penalty_max=0.45,
                strong_edge_to_cost_multiple_min=1.0,
                major_min_meaningful_notional_usd=120.0,
                major_strong_min_entry_notional_usd=180.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 10.0,
            "futures_available_balance_usd": 10.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        decision = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            predictability_score=70.0,
            gross_expected_edge_bps=18.0,
            estimated_round_trip_cost_bps=10.0,
            net_expected_edge_bps=8.0,
            order_intent_notional_usd=120.0,
        )

        capped = session._cap_live_order_decision(decision, reference_price=100.0)

        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("MIN_MEANINGFUL_NOTIONAL", capped.rejection_reasons)

    def test_cap_live_order_decision_raises_major_medium_entry_to_medium_notional(self) -> None:
        settings = replace(
            self.settings,
            mode_thresholds=replace(
                self.settings.mode_thresholds,
                futures_score_min=60.0,
            ),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                min_entry_net_edge_bps=4.0,
                major_medium_min_entry_notional_usd=140.0,
                major_medium_size_boost_multiplier=1.15,
                soft_liquidity_floor=0.24,
                pyramid_min_predictability_score=58.0,
                pyramid_min_trend_strength=0.5,
                pyramid_min_volume_confirmation=0.4,
                pyramid_min_net_edge_bps=6.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 250.0,
            "futures_available_balance_usd": 250.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        decision = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            predictability_score=60.0,
            gross_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            net_expected_edge_bps=6.0,
            order_intent_notional_usd=120.0,
        )

        capped = session._cap_live_order_decision(decision, reference_price=100.0)

        self.assertEqual(capped.final_mode, "futures")
        self.assertEqual(capped.order_intent_notional_usd, 140.0)

    def test_cap_live_order_decision_relaxes_internal_caps_for_major_strong_signal(self) -> None:
        relaxed_settings = replace(
            self.settings,
            mode_thresholds=replace(
                self.settings.mode_thresholds,
                futures_score_min=60.0,
            ),
            risk=replace(
                self.settings.risk,
                max_total_notional_fraction=0.6,
            ),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                strong_score_buffer=0.5,
                strong_trend_strength_min=0.6,
                strong_volume_confirmation_min=0.5,
                strong_liquidity_min=0.42,
                strong_volatility_penalty_max=0.55,
                strong_overheat_penalty_max=0.45,
                strong_edge_to_cost_multiple_min=1.0,
                major_strong_total_notional_fraction_relaxation=0.22,
                major_strong_safety_cap_fraction=0.92,
            ),
        )
        strict_settings = replace(
            relaxed_settings,
            futures_exposure=replace(
                relaxed_settings.futures_exposure,
                major_strong_total_notional_fraction_relaxation=0.0,
                major_strong_safety_cap_fraction=0.5,
            ),
        )
        session = self._build_session(settings=relaxed_settings)
        strict_session = self._build_session(settings=strict_settings)
        self._seed_weak_futures_position(
            session,
            symbol="DOGEUSDT",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            entry_price=100.0,
            current_price=100.0,
            quantity=40.0,
        )
        session.paper_positions["DOGEUSDT"].exchange_synced = True
        self._seed_weak_futures_position(
            strict_session,
            symbol="DOGEUSDT",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            entry_price=100.0,
            current_price=100.0,
            quantity=40.0,
        )
        strict_session.paper_positions["DOGEUSDT"].exchange_synced = True
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 600.0,
            "futures_available_balance_usd": 600.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        strict_session.capital_report = dict(session.capital_report)
        decision = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            predictability_score=70.0,
            gross_expected_edge_bps=18.0,
            estimated_round_trip_cost_bps=10.0,
            net_expected_edge_bps=8.0,
            order_intent_notional_usd=3500.0,
        )

        capped = session._cap_live_order_decision(decision, reference_price=100.0)
        strict_capped = strict_session._cap_live_order_decision(decision, reference_price=100.0)

        self.assertEqual(capped.final_mode, "futures")
        self.assertGreater(capped.order_intent_notional_usd, strict_capped.order_intent_notional_usd)
        self.assertEqual(capped.order_intent_notional_usd, 469.2)
        self.assertEqual(strict_capped.order_intent_notional_usd, 255.0)

    def test_cap_live_order_decision_raises_major_medium_entry_to_minimum_notional(self) -> None:
        settings = replace(
            self.settings,
            mode_thresholds=replace(
                self.settings.mode_thresholds,
                futures_score_min=60.0,
            ),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                min_entry_net_edge_bps=4.0,
                major_medium_min_entry_notional_usd=140.0,
                major_medium_size_boost_multiplier=1.2,
                pyramid_min_predictability_score=58.0,
                pyramid_min_net_edge_bps=6.0,
                pyramid_min_trend_strength=0.5,
                pyramid_min_volume_confirmation=0.4,
                strong_score_buffer=10.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 250.0,
            "futures_available_balance_usd": 250.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        decision = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            predictability_score=62.0,
            gross_expected_edge_bps=19.0,
            estimated_round_trip_cost_bps=10.0,
            net_expected_edge_bps=9.0,
            order_intent_notional_usd=120.0,
        )

        capped = session._cap_live_order_decision(decision, reference_price=100.0)

        self.assertEqual(capped.final_mode, "futures")
        self.assertEqual(capped.order_intent_notional_usd, 140.0)

    def test_cap_live_order_decision_relaxes_internal_caps_for_major_medium_signal(self) -> None:
        relaxed_settings = replace(
            self.settings,
            mode_thresholds=replace(
                self.settings.mode_thresholds,
                futures_score_min=60.0,
            ),
            risk=replace(
                self.settings.risk,
                max_total_notional_fraction=0.6,
            ),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                min_entry_net_edge_bps=4.0,
                major_medium_min_entry_notional_usd=140.0,
                major_medium_total_notional_fraction_relaxation=0.08,
                major_medium_safety_cap_fraction=0.7,
                pyramid_min_predictability_score=58.0,
                pyramid_min_net_edge_bps=6.0,
                pyramid_min_trend_strength=0.5,
                pyramid_min_volume_confirmation=0.4,
                strong_score_buffer=10.0,
            ),
        )
        strict_settings = replace(
            relaxed_settings,
            futures_exposure=replace(
                relaxed_settings.futures_exposure,
                major_medium_total_notional_fraction_relaxation=0.0,
                major_medium_safety_cap_fraction=0.5,
            ),
        )
        session = self._build_session(settings=relaxed_settings)
        strict_session = self._build_session(settings=strict_settings)
        self._seed_weak_futures_position(
            session,
            symbol="DOGEUSDT",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            entry_price=100.0,
            current_price=100.0,
            quantity=40.0,
        )
        session.paper_positions["DOGEUSDT"].exchange_synced = True
        self._seed_weak_futures_position(
            strict_session,
            symbol="DOGEUSDT",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            entry_price=100.0,
            current_price=100.0,
            quantity=40.0,
        )
        strict_session.paper_positions["DOGEUSDT"].exchange_synced = True
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 600.0,
            "futures_available_balance_usd": 600.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        strict_session.capital_report = dict(session.capital_report)
        decision = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            predictability_score=62.0,
            gross_expected_edge_bps=19.0,
            estimated_round_trip_cost_bps=10.0,
            net_expected_edge_bps=9.0,
            order_intent_notional_usd=3500.0,
        )

        capped = session._cap_live_order_decision(decision, reference_price=100.0)
        strict_capped = strict_session._cap_live_order_decision(decision, reference_price=100.0)

        self.assertEqual(capped.final_mode, "futures")
        self.assertGreater(capped.order_intent_notional_usd, strict_capped.order_intent_notional_usd)

    def test_session_trims_futures_position_on_profit_protection_retrace(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=entry_time),
            state=state,
            timestamp=entry_time,
        )

        peak_time = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state.last_trade_price = 104.0
        session._record_decision(
            decision=make_decision(timestamp=peak_time, order_intent_notional_usd=1100.0),
            state=state,
            timestamp=peak_time,
        )

        self.assertEqual(len(session.closed_trades), 0)
        self.assertAlmostEqual(session.paper_positions["BTCUSDT"].peak_roe_percent, 8.0)

        retrace_time = datetime(2026, 3, 8, 12, 15, tzinfo=timezone.utc)
        state.last_trade_price = 102.5
        session._record_decision(
            decision=make_decision(timestamp=retrace_time, order_intent_notional_usd=1050.0),
            state=state,
            timestamp=retrace_time,
        )

        position = session.paper_positions["BTCUSDT"]
        self.assertEqual(len(session.closed_trades), 1)
        self.assertEqual(session.closed_trades[0]["exit_reason"], "PROFIT_PROTECTION_PARTIAL_TAKE_PROFIT")
        self.assertTrue(position.partial_take_profit_taken)
        self.assertAlmostEqual(position.quantity_remaining, position.quantity_opened * 0.5)
        self.assertEqual(position.active_stop_price, position.entry_price)

    def test_session_does_not_trim_futures_position_on_small_profit_retrace_noise(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=entry_time),
            state=state,
            timestamp=entry_time,
        )

        peak_time = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state.last_trade_price = 104.0
        session._record_decision(
            decision=make_decision(timestamp=peak_time, order_intent_notional_usd=1100.0),
            state=state,
            timestamp=peak_time,
        )

        noise_time = datetime(2026, 3, 8, 12, 15, tzinfo=timezone.utc)
        state.last_trade_price = 103.2
        session._record_decision(
            decision=make_decision(timestamp=noise_time, order_intent_notional_usd=1075.0),
            state=state,
            timestamp=noise_time,
        )

        position = session.paper_positions["BTCUSDT"]
        self.assertEqual(len(session.closed_trades), 0)
        self.assertFalse(position.partial_take_profit_taken)
        self.assertAlmostEqual(position.peak_roe_percent, 8.0)
        self.assertEqual(position.active_stop_price, 95.0)

    def test_session_trims_futures_position_on_proactive_roe_threshold(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=entry_time),
            state=state,
            timestamp=entry_time,
        )

        trigger_time = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state.last_trade_price = 105.0
        session._record_decision(
            decision=make_decision(timestamp=trigger_time, order_intent_notional_usd=1100.0),
            state=state,
            timestamp=trigger_time,
        )

        position = session.paper_positions["BTCUSDT"]
        self.assertEqual(len(session.closed_trades), 1)
        self.assertEqual(session.closed_trades[0]["exit_reason"], "PROACTIVE_PARTIAL_TAKE_PROFIT")
        self.assertTrue(position.partial_take_profit_taken)
        self.assertEqual(position.proactive_take_profit_thresholds_hit, (10.0,))
        self.assertAlmostEqual(position.quantity_remaining, position.quantity_opened * 0.75)
        self.assertEqual(position.active_stop_price, position.entry_price)

    def test_major_signal_reallocation_can_replace_non_major_with_relaxed_floor(self) -> None:
        settings = replace(
            self._focus_settings(futures_top_n=1),
            mode_thresholds=replace(
                self._focus_settings(futures_top_n=1).mode_thresholds,
                futures_score_min=60.0,
            ),
            futures_exposure=replace(
                self._focus_settings(futures_top_n=1).futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                major_reallocation_score_advantage_relaxation=3.0,
                major_reallocation_edge_advantage_relaxation_bps=1.0,
                major_reallocation_incremental_pnl_relaxation_usd=0.75,
            ),
        )
        session = self._build_session(settings=settings)
        weak_time = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        self._seed_weak_futures_position(
            session,
            symbol="DOGEUSDT",
            entry_time=weak_time,
            current_price=90.0,
            entry_predictability_score=66.0,
            latest_predictability_score=62.0,
            entry_net_expected_edge_bps=8.0,
            latest_net_expected_edge_bps=2.0,
        )
        session.capital_report = {
            "futures_available_balance_usd": 50.0,
            "futures_execution_balance_usd": 1.0,
            "can_trade_futures_any": True,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_trade_price = 100.0
        managed = session._maybe_reallocate_futures_entry(
            decision=make_decision(
                timestamp=weak_time + timedelta(minutes=10),
                symbol="BTCUSDT",
                predictability_score=64.0,
                gross_expected_edge_bps=24.0,
                net_expected_edge_bps=20.0,
                estimated_round_trip_cost_bps=2.0,
                order_intent_notional_usd=2500.0,
            ),
            state=state,
            timestamp=weak_time + timedelta(minutes=10),
        )
        self.assertEqual(managed.final_mode, "futures")
        self.assertNotIn("MAX_CONCURRENT_FUTURES", managed.rejection_reasons)
        self.assertEqual(session.closed_trades[0]["exit_reason"], "CAPITAL_REALLOCATION")
        self.assertEqual(session.closed_trades[0]["symbol"], "DOGEUSDT")

    def test_session_pyramids_same_symbol_winner_once(self) -> None:
        settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                pyramid_enabled=True,
                pyramid_major_only=True,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                pyramid_min_roe_percent=0.5,
                pyramid_min_predictability_score=58.0,
                pyramid_min_net_edge_bps=6.0,
                pyramid_min_trend_strength=0.5,
                pyramid_min_volume_confirmation=0.4,
                pyramid_max_adds_per_symbol=1,
                pyramid_size_multiplier=0.4,
            ),
        )
        session = self._build_session(settings=settings)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=entry_time, symbol="BTCUSDT", order_intent_notional_usd=1000.0),
            state=state,
            timestamp=entry_time,
        )
        position = session.paper_positions["BTCUSDT"]
        original_quantity = position.quantity_remaining

        pyramid_time = entry_time + timedelta(minutes=5)
        state.last_trade_price = 101.0
        session._record_decision(
            decision=make_decision(
                timestamp=pyramid_time,
                symbol="BTCUSDT",
                predictability_score=64.0,
                net_expected_edge_bps=10.0,
                order_intent_notional_usd=1000.0,
            ),
            state=state,
            timestamp=pyramid_time,
        )

        position = session.paper_positions["BTCUSDT"]
        self.assertGreater(position.quantity_remaining, original_quantity)
        self.assertEqual(session.futures_pyramid_add_counts["BTCUSDT"], 1)

    def test_session_pyramids_same_symbol_winner_for_non_major_when_enabled(self) -> None:
        settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                pyramid_enabled=True,
                pyramid_major_only=False,
                major_symbols=(),
                pyramid_min_roe_percent=0.5,
                pyramid_min_predictability_score=58.0,
                pyramid_min_net_edge_bps=6.0,
                pyramid_min_trend_strength=0.5,
                pyramid_min_volume_confirmation=0.4,
                pyramid_max_adds_per_symbol=1,
                pyramid_size_multiplier=0.4,
            ),
        )
        session = self._build_session(settings=settings)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=entry_time, symbol="BTCUSDT", order_intent_notional_usd=1000.0),
            state=state,
            timestamp=entry_time,
        )
        original_quantity = session.paper_positions["BTCUSDT"].quantity_remaining

        state.last_trade_price = 101.0
        session._record_decision(
            decision=make_decision(
                timestamp=entry_time + timedelta(minutes=5),
                symbol="BTCUSDT",
                predictability_score=64.0,
                net_expected_edge_bps=10.0,
                order_intent_notional_usd=1000.0,
            ),
            state=state,
            timestamp=entry_time + timedelta(minutes=5),
        )

        self.assertGreater(session.paper_positions["BTCUSDT"].quantity_remaining, original_quantity)
        self.assertEqual(session.futures_pyramid_add_counts["BTCUSDT"], 1)

    def test_session_does_not_retrigger_same_proactive_roe_threshold(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=entry_time),
            state=state,
            timestamp=entry_time,
        )

        first_trigger_time = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state.last_trade_price = 105.0
        session._record_decision(
            decision=make_decision(timestamp=first_trigger_time, order_intent_notional_usd=1100.0),
            state=state,
            timestamp=first_trigger_time,
        )

        second_trigger_time = datetime(2026, 3, 8, 12, 15, tzinfo=timezone.utc)
        state.last_trade_price = 105.5
        session._record_decision(
            decision=make_decision(timestamp=second_trigger_time, order_intent_notional_usd=1120.0),
            state=state,
            timestamp=second_trigger_time,
        )

        position = session.paper_positions["BTCUSDT"]
        self.assertEqual(len(session.closed_trades), 1)
        self.assertEqual(position.proactive_take_profit_thresholds_hit, (10.0,))
        self.assertAlmostEqual(position.quantity_remaining, position.quantity_opened * 0.75)

    def test_session_proactive_take_profit_coexists_with_profit_protection_retrace(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=entry_time),
            state=state,
            timestamp=entry_time,
        )

        proactive_time = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state.last_trade_price = 105.0
        session._record_decision(
            decision=make_decision(timestamp=proactive_time, order_intent_notional_usd=1100.0),
            state=state,
            timestamp=proactive_time,
        )

        peak_time = datetime(2026, 3, 8, 12, 15, tzinfo=timezone.utc)
        state.last_trade_price = 106.0
        session._record_decision(
            decision=make_decision(timestamp=peak_time, order_intent_notional_usd=1150.0),
            state=state,
            timestamp=peak_time,
        )

        retrace_time = datetime(2026, 3, 8, 12, 20, tzinfo=timezone.utc)
        state.last_trade_price = 104.5
        session._record_decision(
            decision=make_decision(timestamp=retrace_time, order_intent_notional_usd=1090.0),
            state=state,
            timestamp=retrace_time,
        )

        position = session.paper_positions["BTCUSDT"]
        self.assertEqual(
            [trade["exit_reason"] for trade in session.closed_trades],
            ["PROACTIVE_PARTIAL_TAKE_PROFIT", "PROFIT_PROTECTION_PARTIAL_TAKE_PROFIT"],
        )
        self.assertTrue(position.profit_protection_retrace_taken)
        self.assertEqual(position.proactive_take_profit_thresholds_hit, (10.0,))
        self.assertAlmostEqual(position.quantity_remaining, position.quantity_opened * 0.375)

    @patch("quant_binance.session.send_telegram_message")
    def test_session_sends_telegram_alerts_for_profit_and_stop(self, mock_send) -> None:
        mock_send.return_value = {"ok": True}
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=entry_time),
            state=state,
            timestamp=entry_time,
        )

        take_profit_time = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state.last_trade_price = 108.0
        session._record_decision(
            decision=make_decision(timestamp=take_profit_time, order_intent_notional_usd=1200.0),
            state=state,
            timestamp=take_profit_time,
        )

        stop_time = datetime(2026, 3, 8, 12, 15, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=stop_time, order_intent_notional_usd=900.0),
            state=state,
            timestamp=stop_time,
        )

        self.assertGreaterEqual(mock_send.call_count, 2)
        self.assertTrue(any("PARTIAL_TAKE_PROFIT" in call.args[0] for call in mock_send.call_args_list))
        self.assertTrue(any("BREAKEVEN_STOP" in call.args[0] for call in mock_send.call_args_list))

    @patch("quant_binance.session.send_telegram_message")
    def test_session_arms_kill_switch_and_alerts_on_daily_loss_limit(self, mock_send) -> None:
        mock_send.return_value = {"ok": True}
        session = self._build_session()
        position = session.paper_positions.setdefault(
            "BTCUSDT",
            __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
                symbol="BTCUSDT",
                market="futures",
                side="long",
                entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
                entry_price=100.0,
                current_price=100.0,
                quantity_opened=30.0,
                quantity_remaining=30.0,
                stop_distance_bps=500.0,
                active_stop_price=95.0,
                best_price=100.0,
                worst_price=100.0,
                entry_predictability_score=82.0,
                entry_liquidity_score=0.8,
            ),
        )
        session._record_closed_trade(
            position=position,
            exit_price=92.0,
            quantity_closed=30.0,
            exit_time=datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc),
            exit_reason="STOP_LOSS",
        )
        self.assertTrue(session.runtime.kill_switch.armed)
        self.assertIn("DAILY_REALIZED_LOSS_LIMIT", session.runtime.kill_switch.reasons)
        self.assertTrue(any("DAILY_REALIZED_LOSS_LIMIT" in call.args[0] for call in mock_send.call_args_list))

    @patch("quant_binance.session.send_telegram_message")
    def test_session_closes_live_position_on_take_profit_roe(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []
                self.tpsl_orders = []

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "total": "0.02",
                            "marginSize": "10",
                            "unrealizedPL": "2.0",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "uTime": "1234567890",
                            "cTime": "1234567890",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "close-1"}

            def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
                self.tpsl_orders.append(order_params)
                return {"status": "SUCCESS", "orderId": "tpsl-1"}

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_price=50000.0,
            current_price=50000.0,
            quantity=0.02,
        )
        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_PROACTIVE_PARTIAL_TAKE_PROFIT")
        self.assertTrue(session.live_orders[0]["partial_exit"])
        self.assertEqual(session.live_orders[0]["quantity"], 0.005)
        self.assertEqual(len(session.rest_client.tpsl_orders), 1)
        self.assertTrue(any("LIVE_POSITION_PROACTIVE_PARTIAL_TAKE_PROFIT" in call.args[0] for call in mock_send.call_args_list))
        session.sync_account()
        self.assertEqual(len(session.live_orders), 1)

    def test_reconcile_live_position_plan_orders_cancels_duplicate_bitget_tpsl_orders(self) -> None:
        class PositionRestClient(FakeRestClient):
            supports_private_reads = True

            def __init__(self) -> None:
                super().__init__()
                self.cancelled_plan_orders = []

            def get_futures_pending_plan_orders(self, *, symbol: str | None = None, plan_type: str = "profit_loss"):  # type: ignore[no-untyped-def]
                return {
                    "orders": [
                        {
                            "symbol": "BTCUSDT",
                            "posSide": "long",
                            "tradeSide": "close",
                            "planType": "profit_plan",
                            "planStatus": "live",
                            "orderId": "profit-old",
                            "clientOid": "profit-old-cid",
                            "uTime": "100",
                        },
                        {
                            "symbol": "BTCUSDT",
                            "posSide": "long",
                            "tradeSide": "close",
                            "planType": "profit_plan",
                            "planStatus": "live",
                            "orderId": "profit-new",
                            "clientOid": "profit-new-cid",
                            "uTime": "200",
                        },
                        {
                            "symbol": "BTCUSDT",
                            "posSide": "long",
                            "tradeSide": "close",
                            "planType": "loss_plan",
                            "planStatus": "live",
                            "orderId": "loss-old",
                            "clientOid": "loss-old-cid",
                            "uTime": "101",
                        },
                        {
                            "symbol": "BTCUSDT",
                            "posSide": "long",
                            "tradeSide": "close",
                            "planType": "loss_plan",
                            "planStatus": "live",
                            "orderId": "loss-new",
                            "clientOid": "loss-new-cid",
                            "uTime": "201",
                        },
                    ]
                }

            def cancel_futures_plan_orders(self, *, symbol: str, order_id_list, plan_type=None):  # type: ignore[no-untyped-def]
                self.cancelled_plan_orders.append((symbol, plan_type, order_id_list))
                return {"status": "SUCCESS"}

        session = self._build_session()
        session.rest_client = PositionRestClient()

        session._reconcile_live_position_plan_orders(
            position={
                "symbol": "BTCUSDT",
                "holdSide": "long",
                "uTime": "1234567890",
                "cTime": "1234567890",
            },
            hold_side="long",
        )

        cancelled = session.rest_client.cancelled_plan_orders
        self.assertEqual(len(cancelled), 2)
        self.assertEqual({item[1] for item in cancelled}, {"profit_plan", "loss_plan"})
        self.assertEqual(
            {entry["orderId"] for _, _, rows in cancelled for entry in rows},
            {"profit-old", "loss-old"},
        )

    @patch("quant_binance.session.send_telegram_message")
    def test_session_uses_reduce_only_payload_for_bitget_one_way_proactive_partial_close(self, mock_send) -> None:
        class PositionRestClient(BitgetRestClient):
            def __init__(self) -> None:
                super().__init__(credentials=None)
                self.placed_orders = []
                self.tpsl_orders = []

            def get_account(self, *, market: str) -> dict[str, object]:
                return {"market": market, "balance": 1000}

            def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, object]:
                return {"market": market, "orders": []}

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "posMode": "one_way_mode",
                            "total": "0.0016",
                            "available": "0.0016",
                            "marginSize": "14.49026",
                            "unrealizedPL": "2.664829999999",
                            "marginRatio": "0.030481094756",
                            "breakEvenPrice": "70839.679387192378",
                            "openPriceAvg": "70785.781250000001",
                            "leverage": "8",
                            "uTime": "1773388807347",
                            "cTime": "1773276221655",
                        }
                    ]
                }

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "close-one-way"}

            def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
                self.tpsl_orders.append(order_params)
                return {"status": "SUCCESS", "orderId": "tpsl-1"}

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_price=70785.78125,
            current_price=70785.78125,
            quantity=0.0016,
            leverage=8,
        )

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["response"]["orderId"], "close-one-way")
        self.assertEqual(len(session.rest_client.placed_orders), 1)
        self.assertEqual(session.rest_client.placed_orders[0][1]["side"], "sell")
        self.assertEqual(session.rest_client.placed_orders[0][1]["reduceOnly"], "YES")
        self.assertNotIn("tradeSide", session.rest_client.placed_orders[0][1])
        self.assertEqual(len(session.rest_client.tpsl_orders), 1)

    @patch("quant_binance.session.send_telegram_message")
    def test_session_retries_bitget_live_take_profit_close_on_one_way_mode_error(self, mock_send) -> None:
        class PositionRestClient(BitgetRestClient):
            def __init__(self) -> None:
                super().__init__(credentials=None)
                self.placed_orders = []
                self.tpsl_orders = []

            def get_account(self, *, market: str) -> dict[str, object]:
                return {"market": market, "balance": 1000}

            def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, object]:
                return {"market": market, "orders": []}

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "posMode": "hedge_mode",
                            "total": "0.0016",
                            "available": "0.0016",
                            "marginSize": "14.49026",
                            "unrealizedPL": "2.664829999999",
                            "marginRatio": "0.030481094756",
                            "breakEvenPrice": "70839.679387192378",
                            "openPriceAvg": "70785.781250000001",
                            "leverage": "8",
                            "uTime": "1773388807347",
                            "cTime": "1773276221655",
                        }
                    ]
                }

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                if len(self.placed_orders) == 1:
                    raise RuntimeError(
                        'Bitget HTTP 400: {"code":"40774","msg":"The order type for unilateral position must also be the unilateral position type."}'
                    )
                return {"status": "SUCCESS", "orderId": "close-40774"}

            def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
                self.tpsl_orders.append(order_params)
                return {"status": "SUCCESS", "orderId": "tpsl-1"}

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_price=70785.78125,
            current_price=70785.78125,
            quantity=0.0016,
            leverage=8,
        )

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_PROACTIVE_PARTIAL_TAKE_PROFIT")
        self.assertTrue(session.live_orders[0]["partial_exit"])
        self.assertEqual(session.live_orders[0]["quantity"], 0.0004)
        self.assertEqual(session.live_orders[0]["response"]["orderId"], "close-40774")
        self.assertEqual(len(session.rest_client.placed_orders), 2)
        self.assertEqual(session.rest_client.placed_orders[0][1]["side"], "buy")
        self.assertEqual(session.rest_client.placed_orders[0][1]["tradeSide"], "close")
        self.assertNotIn("tradeSide", session.rest_client.placed_orders[1][1])
        self.assertEqual(session.rest_client.placed_orders[1][1]["side"], "sell")
        self.assertEqual(session.rest_client.placed_orders[1][1].get("reduceOnly"), "YES")
        self.assertEqual(len(session.rest_client.tpsl_orders), 1)
        self.assertTrue(any("LIVE_POSITION_PROACTIVE_PARTIAL_TAKE_PROFIT" in call.args[0] for call in mock_send.call_args_list))

    @patch("quant_binance.session.send_telegram_message")
    def test_session_retries_bitget_live_take_profit_close_before_treating_22002_as_already_closed(self, mock_send) -> None:
        class PositionRestClient(BitgetRestClient):
            def __init__(self) -> None:
                super().__init__(credentials=None)
                self.placed_orders = []
                self.tpsl_orders = []

            def get_account(self, *, market: str) -> dict[str, object]:
                return {"market": market, "balance": 1000}

            def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, object]:
                return {"market": market, "orders": []}

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "posMode": "hedge_mode",
                            "total": "0.0016",
                            "available": "0.0016",
                            "marginSize": "14.48718",
                            "unrealizedPL": "2.640189999999",
                            "marginRatio": "0.030195709553",
                            "breakEvenPrice": "70839.679387192378",
                            "openPriceAvg": "70785.781250000001",
                            "leverage": "8",
                            "uTime": "1773388807347",
                            "cTime": "1773276221655",
                        }
                    ]
                }

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                if len(self.placed_orders) == 1:
                    raise RuntimeError('Bitget HTTP 400: {"code":"22002","msg":"No position to close"}')
                return {"status": "SUCCESS", "orderId": "close-22002-retry"}

            def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
                self.tpsl_orders.append(order_params)
                return {"status": "SUCCESS", "orderId": "tpsl-1"}

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_price=70785.78125,
            current_price=70785.78125,
            quantity=0.0016,
            leverage=8,
        )

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_PROACTIVE_PARTIAL_TAKE_PROFIT")
        self.assertEqual(session.live_orders[0]["response"]["orderId"], "close-22002-retry")
        self.assertEqual(len(session.rest_client.placed_orders), 2)
        self.assertEqual(session.rest_client.placed_orders[0][1]["side"], "buy")
        self.assertEqual(session.rest_client.placed_orders[0][1]["tradeSide"], "close")
        self.assertNotIn("tradeSide", session.rest_client.placed_orders[1][1])
        self.assertEqual(session.rest_client.placed_orders[1][1]["side"], "sell")
        self.assertEqual(session.rest_client.placed_orders[1][1].get("reduceOnly"), "YES")
        self.assertEqual(len(session.rest_client.tpsl_orders), 1)
        self.assertTrue(any("LIVE_POSITION_PROACTIVE_PARTIAL_TAKE_PROFIT" in call.args[0] for call in mock_send.call_args_list))

    @patch("quant_binance.session.send_telegram_message")
    def test_session_uses_hedge_close_payload_for_bitget_full_stop_loss_close(self, mock_send) -> None:
        class PositionRestClient(BitgetRestClient):
            def __init__(self) -> None:
                super().__init__(credentials=None)
                self.placed_orders = []

            def get_account(self, *, market: str) -> dict[str, object]:
                return {"market": market, "balance": 1000}

            def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, object]:
                return {"market": market, "orders": []}

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "short",
                            "posMode": "hedge_mode",
                            "total": "0.0016",
                            "available": "0.0016",
                            "marginSize": "0.8",
                            "unrealizedPL": "-0.6",
                            "marginRatio": "0.030195709553",
                            "breakEvenPrice": "70839.679387192378",
                            "openPriceAvg": "70785.781250000001",
                            "leverage": "8",
                            "uTime": "1773388807347",
                            "cTime": "1773276221655",
                        }
                    ]
                }

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "close-stop-loss"}

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_STOP_LOSS")
        self.assertFalse(session.live_orders[0]["partial_exit"])
        self.assertEqual(session.live_orders[0]["response"]["orderId"], "close-stop-loss")
        self.assertEqual(len(session.rest_client.placed_orders), 1)
        self.assertEqual(session.rest_client.placed_orders[0][1]["side"], "sell")
        self.assertEqual(session.rest_client.placed_orders[0][1]["tradeSide"], "close")
        self.assertNotIn("reduceOnly", session.rest_client.placed_orders[0][1])
        self.assertTrue(any("LIVE_POSITION_STOP_LOSS" in call.args[0] for call in mock_send.call_args_list))

    @patch("quant_binance.session.send_telegram_message")
    def test_session_retries_bitget_full_live_close_before_treating_22002_as_already_closed(self, mock_send) -> None:
        class PositionRestClient(BitgetRestClient):
            def __init__(self) -> None:
                super().__init__(credentials=None)
                self.placed_orders = []

            def get_account(self, *, market: str) -> dict[str, object]:
                return {"market": market, "balance": 1000}

            def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, object]:
                return {"market": market, "orders": []}

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "short",
                            "posMode": "hedge_mode",
                            "total": "0.0016",
                            "available": "0.0016",
                            "marginSize": "0.8",
                            "unrealizedPL": "-0.6",
                            "marginRatio": "0.030195709553",
                            "breakEvenPrice": "70839.679387192378",
                            "openPriceAvg": "70785.781250000001",
                            "leverage": "8",
                            "uTime": "1773388807347",
                            "cTime": "1773276221655",
                        }
                    ]
                }

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                if len(self.placed_orders) == 1:
                    raise RuntimeError('Bitget HTTP 400: {"code":"22002","msg":"No position to close"}')
                return {"status": "SUCCESS", "orderId": "close-stop-loss-retry"}

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_STOP_LOSS")
        self.assertEqual(session.live_orders[0]["response"]["orderId"], "close-stop-loss-retry")
        self.assertEqual(len(session.rest_client.placed_orders), 2)
        self.assertEqual(session.rest_client.placed_orders[0][1]["side"], "sell")
        self.assertEqual(session.rest_client.placed_orders[0][1]["tradeSide"], "close")
        self.assertEqual(session.rest_client.placed_orders[1][1]["side"], "buy")
        self.assertEqual(session.rest_client.placed_orders[1][1].get("reduceOnly"), "YES")
        self.assertNotIn("tradeSide", session.rest_client.placed_orders[1][1])
        self.assertTrue(any("LIVE_POSITION_STOP_LOSS" in call.args[0] for call in mock_send.call_args_list))

    @patch("quant_binance.session.send_telegram_message")
    def test_session_trims_live_position_on_profit_protection_retrace(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []
                self.tpsl_orders = []
                self.snapshots = [
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "long",
                                "total": "0.02",
                                "marginSize": "10",
                                "unrealizedPL": "0.8",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "uTime": "1234567890",
                                "cTime": "1234567890",
                            }
                        ]
                    },
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "long",
                                "total": "0.02",
                                "marginSize": "10",
                                "unrealizedPL": "0.5",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "uTime": "1234567890",
                                "cTime": "1234567890",
                            }
                        ]
                    },
                ]
                self.position_calls = 0

            def get_positions(self) -> dict[str, object]:
                index = min(self.position_calls, len(self.snapshots) - 1)
                self.position_calls += 1
                return self.snapshots[index]

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "close-1"}

            def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
                self.tpsl_orders.append(order_params)
                return {"status": "SUCCESS", "orderId": "tpsl-1"}

        custom_settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=(),
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=custom_settings)
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_price=50000.0,
            current_price=50000.0,
            quantity=0.02,
        )

        session.sync_account()
        self.assertEqual(len(session.live_orders), 0)

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_PROFIT_PROTECTION")
        self.assertTrue(session.live_orders[0]["partial_exit"])
        self.assertEqual(len(session.rest_client.tpsl_orders), 1)
        self.assertTrue(any("LIVE_POSITION_PROFIT_PROTECTION" in call.args[0] for call in mock_send.call_args_list))

    @patch("quant_binance.session.send_telegram_message")
    def test_session_does_not_trim_live_position_on_small_profit_retrace_noise(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []
                self.tpsl_orders = []
                self.snapshots = [
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "long",
                                "total": "0.02",
                                "marginSize": "10",
                                "unrealizedPL": "0.8",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "uTime": "1234567890",
                                "cTime": "1234567890",
                            }
                        ]
                    },
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "long",
                                "total": "0.02",
                                "marginSize": "10",
                                "unrealizedPL": "0.7",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "uTime": "1234567890",
                                "cTime": "1234567890",
                            }
                        ]
                    },
                ]
                self.position_calls = 0

            def get_positions(self) -> dict[str, object]:
                index = min(self.position_calls, len(self.snapshots) - 1)
                self.position_calls += 1
                return self.snapshots[index]

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "close-1"}

            def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
                self.tpsl_orders.append(order_params)
                return {"status": "SUCCESS", "orderId": "tpsl-1"}

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()

        session.sync_account()
        session.sync_account()

        live_position = session.live_positions_snapshot[0]
        identity = session._live_position_identity(live_position)
        self.assertEqual(len(session.live_orders), 0)
        self.assertEqual(len(session.rest_client.tpsl_orders), 0)
        self.assertAlmostEqual(session.live_peak_roe_by_identity[identity], 8.0)

    @patch("quant_binance.session.send_telegram_message")
    def test_session_holds_soft_stop_loss_when_turnaround_grace_signal_is_present(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "total": "0.02",
                            "marginSize": "10",
                            "unrealizedPL": "-1.1",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "uTime": "1234567890",
                            "cTime": "1234567890",
                        }
                    ]
                }

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                raise AssertionError("soft-stop turnaround grace should not close the live position")

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()
        session.paper_positions["BTCUSDT"] = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="long",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            entry_price=50000.0,
            current_price=49450.0,
            quantity_opened=0.02,
            quantity_remaining=0.02,
            stop_distance_bps=500.0,
            active_stop_price=49500.0,
            best_price=50000.0,
            worst_price=49400.0,
            entry_predictability_score=82.0,
            entry_liquidity_score=0.8,
            latest_predictability_score=61.0,
            latest_liquidity_score=0.62,
            latest_net_expected_edge_bps=6.0,
            latest_decision_time=datetime.now(tz=timezone.utc),
            entry_net_expected_edge_bps=12.0,
            entry_estimated_round_trip_cost_bps=6.0,
            entry_planned_leverage=5,
        )
        session.live_worst_roe_by_identity["BTCUSDT|long|1234567890"] = -13.5

        session.sync_account()

        self.assertEqual(session.live_orders, [])

    @patch("quant_binance.session.send_telegram_message")
    def test_session_holds_major_soft_stop_during_drawdown_grace(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "total": "0.02",
                            "available": "0.02",
                            "marginSize": "10",
                            "unrealizedPL": "-1.05",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1234567901",
                            "cTime": "1234567901",
                        }
                    ]
                }

        mock_send.return_value = {"ok": True}
        settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_drawdown_grace_enabled=True,
                major_drawdown_grace_minutes=90,
                major_drawdown_abort_roe_percent=-12.0,
                major_drawdown_predictability_min=58.0,
                major_drawdown_net_edge_min_bps=4.0,
                major_drawdown_liquidity_min=0.45,
                major_drawdown_signal_max_age_minutes=30,
                take_profit_roe_percent=99.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.rest_client = PositionRestClient()
        self._seed_weak_futures_position(
            session,
            symbol="BTCUSDT",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            current_price=95.0,
            latest_predictability_score=70.0,
            latest_net_expected_edge_bps=8.0,
        )
        session.paper_positions["BTCUSDT"].latest_liquidity_score = 0.7
        session.paper_positions["BTCUSDT"].latest_decision_time = datetime.now(tz=timezone.utc)

        session.sync_account()

        self.assertEqual(session.live_orders, [])

    @patch("quant_binance.session.send_telegram_message")
    def test_session_closes_major_soft_stop_after_drawdown_grace_expires(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "total": "0.02",
                            "available": "0.02",
                            "marginSize": "10",
                            "unrealizedPL": "-1.05",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1234567902",
                            "cTime": "1234567902",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "major-grace-expired"}

        mock_send.return_value = {"ok": True}
        settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_drawdown_grace_enabled=True,
                major_drawdown_grace_minutes=90,
                major_drawdown_abort_roe_percent=-12.0,
                major_drawdown_predictability_min=58.0,
                major_drawdown_net_edge_min_bps=4.0,
                major_drawdown_liquidity_min=0.45,
                major_drawdown_signal_max_age_minutes=30,
                take_profit_roe_percent=99.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.rest_client = PositionRestClient()
        self._seed_weak_futures_position(
            session,
            symbol="BTCUSDT",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            current_price=95.0,
            latest_predictability_score=70.0,
            latest_net_expected_edge_bps=8.0,
        )
        session.paper_positions["BTCUSDT"].latest_liquidity_score = 0.7
        session.paper_positions["BTCUSDT"].latest_decision_time = datetime.now(tz=timezone.utc)
        session.live_major_drawdown_grace_started_at_by_identity["BTCUSDT|long|1234567902"] = datetime.now(tz=timezone.utc) - timedelta(minutes=120)

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_SOFT_STOP_LOSS")

    @patch("quant_binance.session.send_telegram_message")
    def test_session_takes_fast_partial_profit_after_turnaround_from_loss(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []
                self.tpsl_orders = []
                self.snapshots = [
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "long",
                                "total": "0.02",
                                "marginSize": "10",
                                "unrealizedPL": "-1.3",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "openPriceAvg": "50000.0",
                                "uTime": "1234567890",
                                "cTime": "1234567890",
                            }
                        ]
                    },
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "long",
                                "total": "0.02",
                                "available": "0.02",
                                "marginSize": "10",
                                "unrealizedPL": "0.3",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "openPriceAvg": "50000.0",
                                "uTime": "1234567890",
                                "cTime": "1234567890",
                            }
                        ]
                    },
                ]
                self.position_calls = 0

            def get_positions(self) -> dict[str, object]:
                index = min(self.position_calls, len(self.snapshots) - 1)
                self.position_calls += 1
                return self.snapshots[index]

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "turnaround-close-1"}

            def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
                self.tpsl_orders.append(order_params)
                return {"status": "SUCCESS", "orderId": "turnaround-tpsl-1"}

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()
        session.paper_positions["BTCUSDT"] = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="long",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            entry_price=50000.0,
            current_price=49350.0,
            quantity_opened=0.02,
            quantity_remaining=0.02,
            stop_distance_bps=500.0,
            active_stop_price=49500.0,
            best_price=50000.0,
            worst_price=49300.0,
            entry_predictability_score=82.0,
            entry_liquidity_score=0.8,
            latest_predictability_score=63.0,
            latest_liquidity_score=0.65,
            latest_net_expected_edge_bps=7.0,
            latest_decision_time=datetime.now(tz=timezone.utc),
            entry_net_expected_edge_bps=12.0,
            entry_estimated_round_trip_cost_bps=6.0,
            entry_planned_leverage=5,
        )
        session.live_worst_roe_by_identity["BTCUSDT|long|1234567890"] = -15.5

        session.sync_account()
        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_TURNAROUND_TAKE_PROFIT")
        self.assertTrue(session.live_orders[0]["partial_exit"])

    @patch("quant_binance.session.send_telegram_message")
    def test_session_closes_non_core_position_faster(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "DOGEUSDT",
                            "holdSide": "long",
                            "total": "100",
                            "available": "100",
                            "marginSize": "10",
                            "unrealizedPL": "-0.4",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "0.1",
                            "openPriceAvg": "0.1",
                            "uTime": "1234567999",
                            "cTime": "1234567999",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "non-core-close-1"}

        custom_settings = replace(
            self.settings,
            universe=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=custom_settings)
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="DOGEUSDT",
            side="long",
            entry_price=0.1,
            current_price=0.1,
            quantity=100.0,
        )

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_NON_CORE_SOFT_STOP_LOSS")

    @patch("quant_binance.session.send_telegram_message")
    def test_session_non_core_profit_exit_requires_meaningful_usd_profit(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "DOGEUSDT",
                            "holdSide": "long",
                            "total": "100",
                            "available": "100",
                            "marginSize": "10",
                            "unrealizedPL": "0.2",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "0.1",
                            "openPriceAvg": "0.1",
                            "uTime": "1234567998",
                            "cTime": "1234567998",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "non-core-profit-close"}

        custom_settings = replace(
            self.settings,
            universe=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            live_position_risk=replace(
                self.settings.live_position_risk,
                non_core_take_profit_roe_percent=1.0,
                non_core_take_profit_fraction=1.0,
                non_core_take_profit_min_usd=1.0,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=custom_settings)
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_time=datetime(2026, 3, 13, 0, 0, tzinfo=timezone.utc),
            entry_price=50000.0,
            current_price=50000.0,
            quantity=0.02,
        )

        session.sync_account()

        self.assertEqual(len(session.live_orders), 0)

    @patch("quant_binance.session.send_telegram_message")
    def test_session_major_position_holds_longer_before_profit_protection(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []
                self.snapshots = [
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "long",
                                "total": "0.02",
                                "available": "0.02",
                                "marginSize": "10",
                                "unrealizedPL": "0.9",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "openPriceAvg": "50000.0",
                                "uTime": "1234567000",
                                "cTime": "1234567000",
                            }
                        ]
                    },
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "long",
                                "total": "0.02",
                                "available": "0.02",
                                "marginSize": "10",
                                "unrealizedPL": "0.55",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "openPriceAvg": "50000.0",
                                "uTime": "1234567000",
                                "cTime": "1234567000",
                            }
                        ]
                    },
                ]
                self.position_calls = 0

            def get_positions(self) -> dict[str, object]:
                index = min(self.position_calls, len(self.snapshots) - 1)
                self.position_calls += 1
                return self.snapshots[index]

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "major-profit-protect"}

        custom_settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_profit_protection_arm_roe_percent=12.0,
                major_profit_protection_retrace_roe_percent=4.5,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=custom_settings)
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_price=50000.0,
            current_price=50000.0,
            quantity=0.02,
        )

        session.sync_account()
        session.sync_account()

        self.assertEqual(len(session.live_orders), 0)

    @patch("quant_binance.session.send_telegram_message")
    def test_session_closes_major_position_when_holding_too_long_with_small_profit(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "total": "0.02",
                            "available": "0.02",
                            "marginSize": "10",
                            "unrealizedPL": "0.8",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1773475200000",
                            "cTime": "1773475200000",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "major-low-signal-exit"}

        custom_settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_low_signal_max_holding_minutes=180,
                major_low_signal_min_unrealized_usd=1.5,
                major_low_signal_min_roe_percent=2.5,
                take_profit_roe_percent=99.0,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=custom_settings)
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_price=50000.0,
            current_price=50000.0,
            quantity=0.02,
        )

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_MAJOR_LOW_SIGNAL_EXIT")

    @patch("quant_binance.session.send_telegram_message")
    def test_session_keeps_major_position_when_profit_is_meaningful(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "total": "0.02",
                            "available": "0.02",
                            "marginSize": "10",
                            "unrealizedPL": "2.1",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1773475200000",
                            "cTime": "1773475200000",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "should-not-close"}

        custom_settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            ),
            exit_rules=replace(
                self.settings.exit_rules,
                futures_proactive_take_profit_roe_thresholds_percent=(),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_low_signal_max_holding_minutes=180,
                major_low_signal_min_unrealized_usd=1.5,
                major_low_signal_min_roe_percent=2.5,
                take_profit_roe_percent=99.0,
                major_profit_protection_arm_roe_percent=12.0,
                major_profit_protection_retrace_roe_percent=4.5,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=custom_settings)
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_price=50000.0,
            current_price=50000.0,
            quantity=0.02,
        )

        session.sync_account()

        self.assertEqual(len(session.live_orders), 0)

    def test_session_closes_confirmation_pending_entry_when_follow_up_fails(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        pending_entry = make_decision(
            timestamp=entry_time,
            symbol="BTCUSDT",
            final_mode="futures",
            side="long",
            predictability_score=70.0,
            liquidity_score=0.6,
            net_expected_edge_bps=8.0,
            estimated_round_trip_cost_bps=6.0,
            order_intent_notional_usd=1000.0,
        )
        pending_entry = replace(pending_entry, divergence_code="ENTRY_CONFIRMATION_REQUIRED")
        session._record_decision(
            decision=pending_entry,
            state=state,
            timestamp=entry_time,
        )

        self.assertTrue(session.paper_positions["BTCUSDT"].confirmation_pending)

        fail_time = entry_time + timedelta(minutes=5)
        state.last_trade_price = 99.0
        fail_decision = make_decision(
            timestamp=fail_time,
            symbol="BTCUSDT",
            final_mode="cash",
            side="flat",
            predictability_score=45.0,
            liquidity_score=0.3,
            net_expected_edge_bps=-1.0,
            order_intent_notional_usd=0.0,
        )
        session._record_decision(
            decision=fail_decision,
            state=state,
            timestamp=fail_time,
        )

        self.assertNotIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.closed_trades[-1]["exit_reason"], "ENTRY_CONFIRMATION_FAILED")

    def test_live_client_oid_changes_between_close_attempts(self) -> None:
        session = self._build_session()
        position = {
            "symbol": "DOGEUSDT",
            "holdSide": "long",
            "uTime": "1234567890",
            "cTime": "1234567890",
        }
        first = session._live_client_oid(position=position, reason="LIVE_POSITION_NON_CORE_PROFIT_EXIT", suffix="close")
        second = session._live_client_oid(position=position, reason="LIVE_POSITION_NON_CORE_PROFIT_EXIT", suffix="close")
        self.assertNotEqual(first, second)
        self.assertIn("DOGEUSDT", first)

    def test_major_partial_exit_fraction_is_upscaled_for_fee_sensitive_reason(self) -> None:
        settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_partial_exit_fraction=0.75,
            ),
        )
        session = self._build_session(settings=settings)
        fraction = session._effective_live_partial_exit_fraction(
            position={"symbol": "BTCUSDT"},
            reason="LIVE_POSITION_PROFIT_PROTECTION",
            fraction=0.5,
        )
        self.assertEqual(fraction, 0.75)

    def test_partial_exit_mode_blocks_different_follow_up_mode_during_cooldown(self) -> None:
        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                partial_exit_min_interval_minutes=60,
            ),
        )
        session = self._build_session(settings=settings)
        identity = "BTCUSDT|long|1234567890"
        now = datetime.now(tz=timezone.utc)
        session.live_partial_exit_last_at_by_identity[identity] = now
        session.live_partial_exit_mode_by_identity[identity] = "protection"

        self.assertFalse(
            session._can_trigger_live_partial_exit(
                identity=identity,
                reason="LIVE_POSITION_TURNAROUND_TAKE_PROFIT",
                now=now,
            )
        )

    @patch("quant_binance.session.send_telegram_message")
    def test_close_live_position_uses_full_close_when_partial_below_min_quantity(self, mock_send) -> None:
        class PositionRestClient(BitgetRestClient):
            def __init__(self) -> None:
                super().__init__(credentials=None)
                self.placed_orders = []

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "full-close-min-qty"}

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()
        session.capital_report = {
            "futures_requirements": [
                {"symbol": "DOGEUSDT", "min_notional_usd": 5.0, "min_quantity": 100.0},
            ]
        }

        session._close_live_position(
            position={
                "symbol": "DOGEUSDT",
                "holdSide": "long",
                "total": "150",
                "available": "150",
                "uTime": "1234567001",
                "cTime": "1234567001",
            },
            reason="LIVE_POSITION_NON_CORE_PROFIT_EXIT",
            fraction=0.5,
        )

        self.assertEqual(len(session.rest_client.placed_orders), 1)
        self.assertEqual(session.rest_client.placed_orders[0][1]["size"], "150.00000000")

    @patch("quant_binance.session.send_telegram_message")
    def test_close_live_position_rounds_partial_close_down_to_bitget_step(self, mock_send) -> None:
        class PositionRestClient(BitgetRestClient):
            def __init__(self) -> None:
                super().__init__(credentials=None)
                self.placed_orders = []

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "step-close-1"}

            def get_exchange_info(self, *, market: str) -> dict[str, object]:
                return {
                    "symbols": [
                        {
                            "symbol": "BCHUSDT",
                            "raw": {
                                "symbol": "BCHUSDT",
                                "minTradeNum": "0.01",
                                "sizeMultiplier": "0.01",
                            },
                        }
                    ]
                }

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()
        session.live_order_executor = None
        session.capital_report = {
            "futures_requirements": [
                {"symbol": "BCHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01},
            ]
        }

        session._close_live_position(
            position={
                "symbol": "BCHUSDT",
                "holdSide": "long",
                "total": "0.03",
                "available": "0.03",
                "uTime": "1234567002",
                "cTime": "1234567002",
            },
            reason="LIVE_POSITION_NON_CORE_PROFIT_EXIT",
            fraction=0.5,
        )

        self.assertEqual(len(session.rest_client.placed_orders), 1)
        self.assertEqual(session.rest_client.placed_orders[0][1]["size"], "0.01")

    @patch("quant_binance.session.send_telegram_message")
    def test_close_live_position_skips_partial_profit_when_after_fee_too_small(self, mock_send) -> None:
        class PositionRestClient(BitgetRestClient):
            def __init__(self) -> None:
                super().__init__(credentials=None)
                self.placed_orders = []

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "should-not-fire"}

        mock_send.return_value = {"ok": True}
        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                partial_exit_min_expected_after_fee_usd=1.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.rest_client = PositionRestClient()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_trade_price = 50010.0

        session._close_live_position(
            position={
                "symbol": "BTCUSDT",
                "holdSide": "long",
                "total": "0.02",
                "available": "0.02",
                "breakEvenPrice": "50000.0",
                "openPriceAvg": "50000.0",
                "uTime": "1234567003",
                "cTime": "1234567003",
            },
            reason="LIVE_POSITION_PROFIT_PROTECTION",
            fraction=0.5,
        )

        self.assertEqual(len(session.rest_client.placed_orders), 0)
        self.assertEqual(len(session.live_orders), 0)

    @patch("quant_binance.session.send_telegram_message")
    def test_close_live_position_executes_partial_profit_when_after_fee_is_meaningful(self, mock_send) -> None:
        class PositionRestClient(BitgetRestClient):
            def __init__(self) -> None:
                super().__init__(credentials=None)
                self.placed_orders = []
                self.tpsl_orders = []

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "partial-profit-1"}

            def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
                self.tpsl_orders.append(order_params)
                return {"status": "SUCCESS", "orderId": "tpsl-1"}

        mock_send.return_value = {"ok": True}
        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                partial_exit_min_expected_after_fee_usd=1.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.rest_client = PositionRestClient()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_trade_price = 50350.0

        session._close_live_position(
            position={
                "symbol": "BTCUSDT",
                "holdSide": "long",
                "total": "0.02",
                "available": "0.02",
                "breakEvenPrice": "50000.0",
                "openPriceAvg": "50000.0",
                "uTime": "1234567004",
                "cTime": "1234567004",
            },
            reason="LIVE_POSITION_PROFIT_PROTECTION",
            fraction=0.5,
        )

        self.assertEqual(len(session.rest_client.placed_orders), 1)
        self.assertEqual(len(session.live_orders), 1)
        self.assertTrue(session.live_orders[0]["partial_exit"])

    @patch("quant_binance.session.send_telegram_message")
    def test_session_takes_partial_profit_on_unrealized_pnl_retrace(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []
                self.tpsl_orders = []
                self.snapshots = [
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "long",
                                "total": "0.02",
                                "available": "0.02",
                                "marginSize": "300",
                                "unrealizedPL": "10.0",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "openPriceAvg": "50000.0",
                                "uTime": "1234567890",
                                "cTime": "1234567890",
                            }
                        ]
                    },
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "long",
                                "total": "0.02",
                                "available": "0.02",
                                "marginSize": "300",
                                "unrealizedPL": "6.0",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "openPriceAvg": "50000.0",
                                "uTime": "1234567890",
                                "cTime": "1234567890",
                            }
                        ]
                    },
                ]
                self.position_calls = 0

            def get_positions(self) -> dict[str, object]:
                index = min(self.position_calls, len(self.snapshots) - 1)
                self.position_calls += 1
                return self.snapshots[index]

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "unrealized-close-1"}

            def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
                self.tpsl_orders.append(order_params)
                return {"status": "SUCCESS", "orderId": "unrealized-tpsl-1"}

        custom_settings = replace(
            self.settings,
            exit_rules=replace(
                self.settings.exit_rules,
                futures_profit_protection_arm_roe_percent=99.0,
                futures_profit_protection_retrace_roe_percent=99.0,
                futures_proactive_take_profit_roe_thresholds_percent=(),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                take_profit_roe_percent=99.0,
                position_unrealized_profit_arm_usd=8.0,
                position_unrealized_profit_retrace_usd=3.0,
                position_unrealized_take_profit_fraction=0.25,
                portfolio_unrealized_profit_arm_ratio=1.0,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=custom_settings)
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_price=50000.0,
            current_price=50000.0,
            quantity=0.02,
        )

        session.sync_account()
        self.assertEqual(len(session.live_orders), 0)

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_UNREALIZED_TAKE_PROFIT")
        self.assertTrue(session.live_orders[0]["partial_exit"])
        self.assertEqual(len(session.rest_client.tpsl_orders), 1)

    @patch("quant_binance.session.send_telegram_message")
    def test_session_locks_portfolio_profit_on_unrealized_retrace(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []
                self.tpsl_orders = []
                self.snapshots = [
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "long",
                                "total": "0.02",
                                "available": "0.02",
                                "marginSize": "300",
                                "unrealizedPL": "110.0",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "openPriceAvg": "50000.0",
                                "uTime": "1234567890",
                                "cTime": "1234567890",
                            }
                        ]
                    },
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "long",
                                "total": "0.02",
                                "available": "0.02",
                                "marginSize": "300",
                                "unrealizedPL": "60.0",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "openPriceAvg": "50000.0",
                                "uTime": "1234567890",
                                "cTime": "1234567890",
                            }
                        ]
                    },
                ]
                self.position_calls = 0

            def get_positions(self) -> dict[str, object]:
                index = min(self.position_calls, len(self.snapshots) - 1)
                self.position_calls += 1
                return self.snapshots[index]

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "portfolio-lock-1"}

            def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
                self.tpsl_orders.append(order_params)
                return {"status": "SUCCESS", "orderId": "portfolio-lock-tpsl-1"}

        custom_settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=(),
            ),
            exit_rules=replace(
                self.settings.exit_rules,
                futures_profit_protection_arm_roe_percent=99.0,
                futures_profit_protection_retrace_roe_percent=99.0,
                futures_proactive_take_profit_roe_thresholds_percent=(),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                take_profit_roe_percent=99.0,
                position_unrealized_profit_arm_usd=9999.0,
                portfolio_unrealized_profit_arm_ratio=0.01,
                portfolio_unrealized_profit_retrace_ratio=0.004,
                portfolio_profit_lock_take_profit_fraction=0.25,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=custom_settings)
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_price=50000.0,
            current_price=50000.0,
            quantity=0.02,
        )

        session.sync_account()
        self.assertEqual(len(session.live_orders), 0)

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_PORTFOLIO_PROFIT_LOCK")
        self.assertTrue(session.live_orders[0]["partial_exit"])
        self.assertEqual(len(session.rest_client.tpsl_orders), 1)

    @patch("quant_binance.session.send_telegram_message")
    def test_session_fully_exits_live_positions_when_portfolio_profit_ratio_hits_target(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            exchange_id = "bitget"

            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "posMode": "hedge_mode",
                            "total": "0.02",
                            "available": "0.02",
                            "marginSize": "10",
                            "unrealizedPL": "80.0",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1234567890",
                            "cTime": "1234567890",
                        },
                        {
                            "symbol": "ETHUSDT",
                            "holdSide": "long",
                            "posMode": "hedge_mode",
                            "total": "0.5",
                            "available": "0.5",
                            "marginSize": "10",
                            "unrealizedPL": "40.0",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "2000.0",
                            "openPriceAvg": "2000.0",
                            "uTime": "1234567891",
                            "cTime": "1234567891",
                        },
                    ]
                }

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": f"full-exit-{len(self.placed_orders)}"}

        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                portfolio_full_exit_only=True,
                portfolio_full_exit_profit_ratio=0.01,
                take_profit_roe_percent=99.0,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=settings)
        session.rest_client = PositionRestClient()
        self._seed_strategy_owned_live_position(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_price=50000.0,
            current_price=50000.0,
            quantity=0.02,
        )
        self._seed_strategy_owned_live_position(
            session,
            symbol="ETHUSDT",
            side="long",
            entry_price=2000.0,
            current_price=2000.0,
            quantity=0.5,
        )

        session.sync_account()

        self.assertEqual(len(session.live_orders), 2)
        self.assertTrue(all(item["reason"] == "LIVE_PORTFOLIO_FULL_EXIT" for item in session.live_orders))
        self.assertTrue(all(not item["partial_exit"] for item in session.live_orders))

    @patch("quant_binance.session.send_telegram_message")
    def test_session_keeps_live_position_when_standard_stop_losses_are_disabled(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            exchange_id = "bitget"

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "posMode": "hedge_mode",
                            "total": "0.02",
                            "available": "0.02",
                            "marginSize": "10",
                            "unrealizedPL": "-3.0",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1234567890",
                            "cTime": "1234567890",
                        }
                    ]
                }

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                raise AssertionError("stop-loss close should not fire")

        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                disable_standard_stop_loss_exits=True,
                stop_loss_roe_percent=-1.0,
                soft_stop_roe_percent=-1.0,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=settings)
        session.rest_client = PositionRestClient()

        session.sync_account()

        self.assertEqual(session.live_orders, [])

    @patch("quant_binance.session.send_telegram_message")
    def test_manual_close_sync_reconciles_paper_position_and_applies_one_candle_cooldown(self, mock_send) -> None:
        mock_send.return_value = {"ok": True}
        session = self._build_session()
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        session._record_decision(
            decision=make_decision(timestamp=now),
            state=state,
            timestamp=now,
        )
        self.assertIn("BTCUSDT", session.paper_positions)
        session.live_positions_snapshot = [{"symbol": "BTCUSDT", "holdSide": "long", "total": "0.02", "available": "0.02"}]
        session._reconcile_manual_live_closes(
            previous_live_positions=session.live_positions_snapshot,
            previous_account_snapshot={},
        )
        self.assertIn("BTCUSDT", session.paper_positions)

        session.live_positions_snapshot = []
        session.open_orders_snapshot = {"orders": {"entrustedList": [{"symbol": "BTCUSDT", "orderId": "open-1"}]}}
        session._reconcile_manual_live_closes(
            previous_live_positions=[{"symbol": "BTCUSDT", "holdSide": "long", "total": "0.02", "available": "0.02"}],
            previous_account_snapshot={},
        )

        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.closed_trades, [])
        self.assertEqual(session.rest_client.cancelled_orders, [])
        self.assertEqual(session.manual_symbol_cooldowns, {})
        mock_send.assert_not_called()

    @patch("quant_binance.session.send_telegram_message")
    def test_order_error_applies_symbol_cooldown(self, mock_send) -> None:
        mock_send.return_value = {"ok": True}
        session = self._build_session()
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        session._apply_order_error_cooldown(
            symbol="ETHUSDT",
            error_message='RuntimeError(\'Bitget HTTP 400: {"code":"45111","msg":"less than the minimum order quantity"}\')',
            timestamp=now,
        )
        self.assertTrue(session._is_order_cooldown_active("ETHUSDT", now))
        self.assertFalse(session._is_order_cooldown_active("ETHUSDT", now + timedelta(seconds=901)))
        self.assertTrue(any("ORDER_COOLDOWN" in call.args[0] for call in mock_send.call_args_list))

    def test_manual_symbol_cooldown_blocks_new_paper_position_open(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        session.manual_symbol_cooldowns["BTCUSDT"] = now + timedelta(minutes=5)
        state.last_trade_price = 100.0

        session._record_decision(
            decision=make_decision(timestamp=now, symbol="BTCUSDT"),
            state=state,
            timestamp=now,
        )

        self.assertNotIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.tested_orders, [])

    def test_order_error_cooldown_blocks_new_paper_position_open(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        session.order_error_cooldowns["BTCUSDT"] = now + timedelta(minutes=5)
        state.last_trade_price = 100.0

        session._record_decision(
            decision=make_decision(timestamp=now, symbol="BTCUSDT"),
            state=state,
            timestamp=now,
        )

        self.assertNotIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.tested_orders, [])

    def test_live_entry_opens_paper_position_only_after_live_order_acceptance(self) -> None:
        class AcceptedLiveExecutor:
            def __init__(self) -> None:
                self.calls = []

            def _exchange_id(self) -> str:
                return "bitget"

            def execute_decision(self, *, decision, reference_price):  # type: ignore[no-untyped-def]
                self.calls.append((decision, reference_price))
                return type(
                    "LiveOrderResultStub",
                    (),
                    {
                        "symbol": decision.symbol,
                        "market": decision.final_mode,
                        "side": decision.side,
                        "quantity": round(decision.order_intent_notional_usd / reference_price, 8),
                        "accepted": True,
                        "response": {"status": "SUCCESS", "orderId": "live-1"},
                        "protection_orders": (),
                        "protection_error": "",
                    },
                )()

            def pop_last_preflight_rejection(self):  # type: ignore[no-untyped-def]
                return None

        session = self._build_session()
        session.order_tester = None
        session.live_order_executor = AcceptedLiveExecutor()  # type: ignore[assignment]
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state.last_trade_price = 100.0

        session._record_decision(
            decision=make_decision(timestamp=now, symbol="BTCUSDT"),
            state=state,
            timestamp=now,
        )

        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(len(session.live_orders), 1)

    @patch("quant_binance.session.send_telegram_message")
    def test_live_entry_sends_telegram_alert_on_acceptance(self, mock_send) -> None:
        class AcceptedLiveExecutor:
            def _exchange_id(self) -> str:
                return "bitget"

            def execute_decision(self, *, decision, reference_price):  # type: ignore[no-untyped-def]
                return type(
                    "LiveOrderResultStub",
                    (),
                    {
                        "symbol": decision.symbol,
                        "market": decision.final_mode,
                        "side": decision.side,
                        "quantity": round(decision.order_intent_notional_usd / reference_price, 8),
                        "accepted": True,
                        "response": {"status": "SUCCESS", "orderId": "live-telegram-1"},
                        "protection_orders": (),
                        "protection_error": "",
                    },
                )()

            def pop_last_preflight_rejection(self):  # type: ignore[no-untyped-def]
                return None

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.order_tester = None
        session.live_order_executor = AcceptedLiveExecutor()  # type: ignore[assignment]
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state.last_trade_price = 100.0

        session._record_decision(
            decision=make_decision(timestamp=now, symbol="BTCUSDT"),
            state=state,
            timestamp=now,
        )

        self.assertTrue(any("[LIVE_ENTRY] BTCUSDT" in call.args[0] for call in mock_send.call_args_list))
        self.assertEqual(len(session.telegram_alerts), 1)

    @patch("quant_binance.session.telegram_report_only_enabled", return_value=True)
    @patch("quant_binance.session.send_telegram_message")
    def test_report_only_mode_records_alert_without_sending_immediately(self, mock_send, mock_report_only) -> None:
        session = self._build_session()
        session._send_telegram_alert(key="k1", text="[LIVE_ENTRY] BTCUSDT")

        mock_report_only.assert_called_once()
        mock_send.assert_not_called()
        self.assertEqual(session.telegram_alerts[0]["result"]["reason"], "report_only_mode")

    def test_live_entry_preflight_rejection_does_not_open_paper_position(self) -> None:
        class RejectingLiveExecutor:
            def __init__(self) -> None:
                self.rejection = {
                    "symbol": "BTCUSDT",
                    "market": "futures",
                    "reason": "BITGET_MAX_OPEN_ZERO",
                    "message": "Bitget preflight rejected order because max openable quantity is 0.",
                }

            def _exchange_id(self) -> str:
                return "bitget"

            def execute_decision(self, *, decision, reference_price):  # type: ignore[no-untyped-def]
                return None

            def pop_last_preflight_rejection(self):  # type: ignore[no-untyped-def]
                rejection = dict(self.rejection)
                self.rejection = None
                return rejection

        session = self._build_session()
        session.order_tester = None
        session.live_order_executor = RejectingLiveExecutor()  # type: ignore[assignment]
        session._refresh_account_state_after_live_order_activity = Mock()  # type: ignore[method-assign]
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state.last_trade_price = 100.0

        session._record_decision(
            decision=make_decision(timestamp=now, symbol="BTCUSDT"),
            state=state,
            timestamp=now,
        )

        self.assertNotIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.live_orders, [])
        self.assertIn("BTCUSDT", session.order_error_cooldowns)
        self.assertNotIn("BTCUSDT", session.manual_symbol_cooldowns)
        session._refresh_account_state_after_live_order_activity.assert_called_once_with(
            symbol="BTCUSDT",
            timestamp=now,
            stage="live_order_preflight",
            reason="preflight_capacity",
        )

    def test_stale_fingerprint_suppression_clears_fingerprint_and_records_watchdog_event(self) -> None:
        class CountingLiveExecutor:
            def __init__(self) -> None:
                self.calls = 0

            def _exchange_id(self) -> str:
                return "bitget"

            def execute_decision(self, *, decision, reference_price):  # type: ignore[no-untyped-def]
                self.calls += 1
                return type(
                    "LiveOrderResultStub",
                    (),
                    {
                        "symbol": decision.symbol,
                        "market": decision.final_mode,
                        "side": decision.side,
                        "quantity": round(decision.order_intent_notional_usd / reference_price, 8),
                        "accepted": True,
                        "response": {"status": "SUCCESS", "orderId": f"live-{self.calls}"},
                        "protection_orders": (),
                        "protection_error": "",
                    },
                )()

            def pop_last_preflight_rejection(self):  # type: ignore[no-untyped-def]
                return None

        session = self._build_session()
        session.order_tester = None
        executor = CountingLiveExecutor()
        session.live_order_executor = executor  # type: ignore[assignment]
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        decision = make_decision(timestamp=now, symbol="BTCUSDT")
        stale_fingerprint = session._execution_fingerprint(decision)
        session.last_executed_fingerprint_by_symbol["BTCUSDT"] = stale_fingerprint
        state.last_trade_price = 100.0

        session._record_decision(
            decision=decision,
            state=state,
            timestamp=now,
        )

        self.assertEqual(executor.calls, 0)
        self.assertNotIn("BTCUSDT", session.last_executed_fingerprint_by_symbol)
        self.assertEqual(
            session.self_healing.recent_events[-1].category,
            "live_entry_starvation",
        )

        session._record_decision(
            decision=make_decision(timestamp=now + timedelta(minutes=5), symbol="BTCUSDT"),
            state=state,
            timestamp=now + timedelta(minutes=5),
        )

        self.assertEqual(executor.calls, 1)
        self.assertIn("BTCUSDT", session.paper_positions)

    def test_repeated_live_entry_no_result_triggers_watchdog_cooldown(self) -> None:
        class NoResultLiveExecutor:
            def _exchange_id(self) -> str:
                return "bitget"

            def execute_decision(self, *, decision, reference_price):  # type: ignore[no-untyped-def]
                return None

            def pop_last_preflight_rejection(self):  # type: ignore[no-untyped-def]
                return None

        session = self._build_session()
        session.order_tester = None
        session.live_order_executor = NoResultLiveExecutor()  # type: ignore[assignment]
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_trade_price = 100.0
        base = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)

        for idx in range(3):
            when = base + timedelta(minutes=idx * 5)
            session._record_decision(
                decision=make_decision(timestamp=when, symbol="BTCUSDT"),
                state=state,
                timestamp=when,
            )

        self.assertNotIn("BTCUSDT", session.paper_positions)
        self.assertIn("BTCUSDT", session.manual_symbol_cooldowns)
        self.assertEqual(
            session.self_healing.recent_events[-1].category,
            "live_entry_starvation",
        )
        self.assertEqual(
            session.self_healing.recent_events[-1].action,
            "symbol_cooldown",
        )

    def test_loss_combo_prunes_matching_symbol_direction_time_bucket(self) -> None:
        settings = replace(
            self.settings,
            loss_combo_downgrade=replace(
                self.settings.loss_combo_downgrade,
                enabled=True,
                time_bucket_minutes=240,
                prune_loss_usd=2.0,
            ),
        )
        session = self._build_session(settings=settings)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        entry_time = datetime(2026, 3, 8, 1, 5, tzinfo=timezone.utc)
        self._record_closed_loss_trade(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_time=entry_time,
            exit_time=entry_time + timedelta(minutes=10),
            realized_loss_usd=3.0,
        )

        decision_time = datetime(2026, 3, 8, 3, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=decision_time, symbol="BTCUSDT", side="long"),
            state=state,
            timestamp=decision_time,
        )

        self.assertEqual(session.decisions[-1].final_mode, "cash")
        self.assertEqual(session.decisions[-1].side, "flat")
        self.assertIn("LOSS_COMBO_PRUNE", session.decisions[-1].rejection_reasons)
        self.assertEqual(session.paper_positions, {})

    def test_loss_combo_observe_only_marks_symbol_in_summary(self) -> None:
        settings = replace(
            self.settings,
            loss_combo_downgrade=replace(
                self.settings.loss_combo_downgrade,
                enabled=True,
                time_bucket_minutes=240,
                observe_only_loss_usd=2.0,
            ),
        )
        session = self._build_session(settings=settings)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        summary_path = ROOT / "tests" / "tmp_loss_combo_summary.json"
        state_path = ROOT / "tests" / "tmp_loss_combo_state.json"
        entry_time = datetime(2026, 3, 8, 1, 5, tzinfo=timezone.utc)
        self._record_closed_loss_trade(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_time=entry_time,
            exit_time=entry_time + timedelta(minutes=10),
            realized_loss_usd=3.0,
        )

        decision_time = datetime(2026, 3, 8, 2, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=decision_time, symbol="BTCUSDT", side="long"),
            state=state,
            timestamp=decision_time,
        )

        try:
            summary = session.flush(summary_path=summary_path, state_path=state_path)
            self.assertIn("LOSS_COMBO_OBSERVE_ONLY", session.decisions[-1].rejection_reasons)
            self.assertIn("OBSERVE_ONLY_SYMBOL", session.decisions[-1].rejection_reasons)
            self.assertEqual(summary["observe_only_symbols"], ["BTCUSDT"])
        finally:
            if summary_path.exists():
                summary_path.unlink()
            if state_path.exists():
                state_path.unlink()

    def test_loss_combo_cooldown_blocks_then_relaxes_to_observe_only_after_expiry(self) -> None:
        settings = replace(
            self.settings,
            loss_combo_downgrade=replace(
                self.settings.loss_combo_downgrade,
                enabled=True,
                time_bucket_minutes=240,
                prune_loss_usd=2.0,
                observe_only_loss_usd=4.0,
                cooldown_loss_usd=6.0,
                cooldown_minutes=30,
            ),
        )
        session = self._build_session(settings=settings)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        first_entry_time = datetime(2026, 3, 8, 1, 5, tzinfo=timezone.utc)
        second_entry_time = datetime(2026, 3, 8, 1, 40, tzinfo=timezone.utc)
        self._record_closed_loss_trade(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_time=first_entry_time,
            exit_time=first_entry_time + timedelta(minutes=10),
            realized_loss_usd=3.0,
        )
        second_exit_time = second_entry_time + timedelta(minutes=10)
        self._record_closed_loss_trade(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_time=second_entry_time,
            exit_time=second_exit_time,
            realized_loss_usd=3.0,
        )

        combo_key = session.closed_trades[-1]["loss_combo_key"]
        self.assertEqual(
            session.loss_combo_cooldowns[str(combo_key)],
            second_exit_time + timedelta(minutes=30),
        )

        blocked_time = datetime(2026, 3, 8, 2, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=blocked_time, symbol="BTCUSDT", side="long"),
            state=state,
            timestamp=blocked_time,
        )
        self.assertIn("LOSS_COMBO_COOLDOWN", session.decisions[-1].rejection_reasons)

        relaxed_time = datetime(2026, 3, 8, 2, 25, tzinfo=timezone.utc)
        session._record_decision(
            decision=make_decision(timestamp=relaxed_time, symbol="BTCUSDT", side="long"),
            state=state,
            timestamp=relaxed_time,
        )
        self.assertIn("LOSS_COMBO_OBSERVE_ONLY", session.decisions[-1].rejection_reasons)
        self.assertNotIn("LOSS_COMBO_COOLDOWN", session.decisions[-1].rejection_reasons)

    def test_loss_combo_ignores_partial_loss_closes(self) -> None:
        settings = replace(
            self.settings,
            loss_combo_downgrade=replace(
                self.settings.loss_combo_downgrade,
                enabled=True,
                time_bucket_minutes=240,
                prune_loss_usd=2.0,
            ),
        )
        session = self._build_session(settings=settings)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        entry_time = datetime(2026, 3, 8, 1, 5, tzinfo=timezone.utc)
        self._record_closed_loss_trade(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_time=entry_time,
            exit_time=entry_time + timedelta(minutes=10),
            realized_loss_usd=3.0,
            quantity_opened=2.0,
            quantity_closed=1.0,
        )

        decision_time = datetime(2026, 3, 8, 2, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=decision_time, symbol="BTCUSDT", side="long"),
            state=state,
            timestamp=decision_time,
        )

        self.assertEqual(session.decisions[-1].final_mode, "futures")
        self.assertNotIn("LOSS_COMBO_PRUNE", session.decisions[-1].rejection_reasons)
        self.assertIn("BTCUSDT", session.paper_positions)

    def test_loss_combo_isolated_by_time_bucket(self) -> None:
        settings = replace(
            self.settings,
            loss_combo_downgrade=replace(
                self.settings.loss_combo_downgrade,
                enabled=True,
                time_bucket_minutes=240,
                prune_loss_usd=2.0,
            ),
        )
        session = self._build_session(settings=settings)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        entry_time = datetime(2026, 3, 8, 1, 5, tzinfo=timezone.utc)
        self._record_closed_loss_trade(
            session,
            symbol="BTCUSDT",
            side="long",
            entry_time=entry_time,
            exit_time=entry_time + timedelta(minutes=10),
            realized_loss_usd=3.0,
        )

        decision_time = datetime(2026, 3, 8, 5, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=decision_time, symbol="BTCUSDT", side="long"),
            state=state,
            timestamp=decision_time,
        )

        self.assertEqual(session.decisions[-1].final_mode, "futures")
        self.assertNotIn("LOSS_COMBO_PRUNE", session.decisions[-1].rejection_reasons)
        self.assertIn("BTCUSDT", session.paper_positions)

    def test_major_futures_signal_reversal_applies_reentry_cooldown(self) -> None:
        settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_reentry_cooldown_minutes=20,
            ),
        )
        session = self._build_session(settings=settings)
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        position = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="long",
            entry_time=now - timedelta(minutes=30),
            entry_price=100.0,
            current_price=99.0,
            quantity_opened=1.0,
            quantity_remaining=1.0,
            stop_distance_bps=500.0,
            active_stop_price=95.0,
            best_price=101.0,
            worst_price=98.0,
            entry_predictability_score=70.0,
            entry_liquidity_score=0.7,
            latest_predictability_score=55.0,
            latest_liquidity_score=0.6,
            latest_net_expected_edge_bps=2.0,
            latest_decision_time=now,
            entry_net_expected_edge_bps=8.0,
            entry_estimated_round_trip_cost_bps=6.0,
            entry_planned_leverage=5,
        )

        session._close_position(
            position=position,
            exit_price=99.0,
            timestamp=now,
            exit_reason="SIGNAL_REVERSAL",
        )

        self.assertIn("BTCUSDT", session.manual_symbol_cooldowns)
        self.assertEqual(
            session.manual_symbol_cooldowns["BTCUSDT"],
            now + timedelta(minutes=20),
        )

    def test_major_reversal_exit_requires_more_confirmation_cycles(self) -> None:
        settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_reversal_confirmation_cycles=3,
                major_reversal_min_holding_minutes=0,
            ),
        )
        session = self._build_session(settings=settings)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        entry_time = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=entry_time, symbol="BTCUSDT", side="long"),
            state=state,
            timestamp=entry_time,
        )
        for minute in (5, 10):
            session._record_decision(
                decision=make_decision(
                    timestamp=entry_time + timedelta(minutes=minute),
                    symbol="BTCUSDT",
                    final_mode="cash",
                    side="flat",
                    predictability_score=40.0,
                    net_expected_edge_bps=-1.0,
                    order_intent_notional_usd=0.0,
                ),
                state=state,
                timestamp=entry_time + timedelta(minutes=minute),
            )
            self.assertIn("BTCUSDT", session.paper_positions)

        session._record_decision(
            decision=make_decision(
                timestamp=entry_time + timedelta(minutes=15),
                symbol="BTCUSDT",
                final_mode="cash",
                side="flat",
                predictability_score=40.0,
                net_expected_edge_bps=-1.0,
                order_intent_notional_usd=0.0,
            ),
            state=state,
            timestamp=entry_time + timedelta(minutes=15),
        )

        self.assertNotIn("BTCUSDT", session.paper_positions)

    def test_major_futures_loss_applies_longer_reentry_cooldown(self) -> None:
        settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_loss_reentry_cooldown_minutes=90,
                major_loss_reentry_trigger_usd=1.0,
            ),
        )
        session = self._build_session(settings=settings)
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        position = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="long",
            entry_time=now - timedelta(minutes=30),
            entry_price=100.0,
            current_price=97.5,
            quantity_opened=1.0,
            quantity_remaining=1.0,
            stop_distance_bps=500.0,
            active_stop_price=95.0,
            best_price=101.0,
            worst_price=97.0,
            entry_predictability_score=70.0,
            entry_liquidity_score=0.7,
            latest_predictability_score=55.0,
            latest_liquidity_score=0.6,
            latest_net_expected_edge_bps=2.0,
            latest_decision_time=now,
            entry_net_expected_edge_bps=8.0,
            entry_estimated_round_trip_cost_bps=6.0,
            entry_planned_leverage=5,
        )

        session._close_position(
            position=position,
            exit_price=97.5,
            timestamp=now,
            exit_reason="STOP_LOSS",
        )

        self.assertEqual(
            session.manual_symbol_cooldowns["BTCUSDT"],
            now + timedelta(minutes=90),
        )

    def test_close_live_position_ignores_already_closed_exchange_race(self) -> None:
        class AlreadyClosedRestClient(FakeRestClient):
            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                raise RuntimeError('Bitget HTTP 400: {"code":"22002","msg":"No position to close"}')

        session = self._build_session()
        session.rest_client = AlreadyClosedRestClient()
        session._close_live_position(
            position={"symbol": "BTCUSDT", "holdSide": "long", "total": "0.02", "available": "0.02"},
            reason="LIVE_POSITION_PARTIAL_TAKE_PROFIT",
            fraction=0.5,
        )
        self.assertEqual(len(session.live_orders), 0)

    def test_session_blocks_duplicate_order_submission_while_position_remains_open(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        state.last_trade_price = 100.0
        session._record_decision(
            decision=make_decision(timestamp=entry_time),
            state=state,
            timestamp=entry_time,
        )

        follow_time = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state.last_trade_price = 103.0
        session._record_decision(
            decision=make_decision(timestamp=follow_time, order_intent_notional_usd=1400.0),
            state=state,
            timestamp=follow_time,
        )

        self.assertEqual(len(session.paper_positions), 1)
        self.assertEqual(len(session.closed_trades), 0)
        self.assertEqual(len(session.tested_orders), 1)

    def test_futures_reallocation_has_no_effect_when_entry_is_not_blocked(self) -> None:
        settings = self._focus_settings(futures_top_n=2)
        session = self._build_session(settings=settings)
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        self._seed_weak_futures_position(session, symbol="ETHUSDT", entry_time=now - timedelta(minutes=10))
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        decision = make_decision(
            timestamp=now,
            symbol="SOLUSDT",
            predictability_score=94.0,
            gross_expected_edge_bps=34.0,
            net_expected_edge_bps=24.0,
            estimated_round_trip_cost_bps=6.0,
            order_intent_notional_usd=100.0,
        )

        managed = session._maybe_reallocate_futures_entry(
            decision=decision,
            state=state,
            timestamp=now,
        )

        self.assertEqual(managed, decision)
        self.assertIn("ETHUSDT", session.paper_positions)
        self.assertEqual(session.closed_trades, [])
        self.assertIsNone(session.futures_reallocation_cooldown_until)

    def test_futures_reallocation_triggers_only_for_strict_execution_balance_exception(self) -> None:
        settings = self._focus_settings(futures_top_n=2)
        session = self._build_session(settings=settings)
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        self._seed_weak_futures_position(session, symbol="ETHUSDT", entry_time=now - timedelta(minutes=10))
        session.capital_report = {
            "futures_available_balance_usd": 50.0,
            "futures_execution_balance_usd": 1.0,
            "can_trade_futures_any": True,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        managed = session._maybe_reallocate_futures_entry(
            decision=make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=94.0,
                gross_expected_edge_bps=36.0,
                net_expected_edge_bps=24.0,
                estimated_round_trip_cost_bps=6.0,
                order_intent_notional_usd=2500.0,
            ),
            state=state,
            timestamp=now,
        )

        self.assertEqual(managed.final_mode, "futures")
        self.assertEqual(managed.order_intent_notional_usd, 2500.0)
        self.assertNotIn("ETHUSDT", session.paper_positions)
        self.assertEqual(len(session.closed_trades), 1)
        self.assertEqual(session.closed_trades[0]["exit_reason"], "CAPITAL_REALLOCATION")
        self.assertEqual(session.futures_reallocation_cooldown_until, now + timedelta(minutes=10))

    def test_futures_reallocation_replaces_multiple_weakest_positions_until_capacity_is_sufficient(self) -> None:
        settings = replace(
            self._focus_settings(futures_top_n=2),
            futures_exposure=replace(
                self._focus_settings(futures_top_n=2).futures_exposure,
                major_symbols=(),
            ),
        )
        session = self._build_session(settings=settings)
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        self._seed_weak_futures_position(
            session,
            symbol="ETHUSDT",
            entry_time=now - timedelta(minutes=15),
            current_price=75.0,
            quantity=20.0,
            latest_predictability_score=71.0,
            latest_net_expected_edge_bps=6.0,
        )
        self._seed_weak_futures_position(
            session,
            symbol="SOLUSDT",
            entry_time=now - timedelta(minutes=12),
            current_price=50.0,
            quantity=30.0,
            latest_predictability_score=72.0,
            latest_net_expected_edge_bps=6.0,
        )
        self._seed_weak_futures_position(
            session,
            symbol="XRPUSDT",
            entry_time=now - timedelta(minutes=9),
            current_price=102.0,
            quantity=10.0,
            entry_predictability_score=89.0,
            latest_predictability_score=86.0,
            entry_net_expected_edge_bps=18.0,
            latest_net_expected_edge_bps=16.0,
        )
        session.capital_report = {
            "futures_available_balance_usd": 50.0,
            "futures_execution_balance_usd": 1.0,
            "can_trade_futures_any": True,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        managed = session._maybe_reallocate_futures_entry(
            decision=make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=96.0,
                gross_expected_edge_bps=46.0,
                net_expected_edge_bps=34.0,
                estimated_round_trip_cost_bps=6.0,
                order_intent_notional_usd=2500.0,
            ),
            state=state,
            timestamp=now,
        )

        self.assertEqual(managed.final_mode, "futures")
        self.assertEqual(managed.order_intent_notional_usd, 2500.0)
        self.assertNotIn("ETHUSDT", session.paper_positions)
        self.assertNotIn("SOLUSDT", session.paper_positions)
        self.assertIn("XRPUSDT", session.paper_positions)
        self.assertEqual(
            [trade["symbol"] for trade in session.closed_trades],
            ["ETHUSDT", "SOLUSDT"],
        )
        self.assertTrue(all(trade["exit_reason"] == "CAPITAL_REALLOCATION" for trade in session.closed_trades))
        self.assertEqual(session.futures_reallocation_cooldown_until, now + timedelta(minutes=10))

    def test_futures_reallocation_rejects_multi_replacement_when_aggregated_switching_costs_fail(self) -> None:
        settings = self._focus_settings(futures_top_n=2)
        session = self._build_session(settings=settings)
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        self._seed_weak_futures_position(
            session,
            symbol="ETHUSDT",
            entry_time=now - timedelta(minutes=15),
            current_price=75.0,
            quantity=20.0,
            latest_predictability_score=71.0,
            latest_net_expected_edge_bps=8.0,
        )
        self._seed_weak_futures_position(
            session,
            symbol="SOLUSDT",
            entry_time=now - timedelta(minutes=12),
            current_price=50.0,
            quantity=30.0,
            latest_predictability_score=72.0,
            latest_net_expected_edge_bps=8.0,
        )
        self._seed_weak_futures_position(
            session,
            symbol="XRPUSDT",
            entry_time=now - timedelta(minutes=9),
            current_price=102.0,
            quantity=10.0,
            entry_predictability_score=89.0,
            latest_predictability_score=86.0,
            entry_net_expected_edge_bps=18.0,
            latest_net_expected_edge_bps=16.0,
        )
        session.capital_report = {
            "futures_available_balance_usd": 50.0,
            "futures_execution_balance_usd": 1.0,
            "can_trade_futures_any": True,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        managed = session._maybe_reallocate_futures_entry(
            decision=make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=96.0,
                gross_expected_edge_bps=42.0,
                net_expected_edge_bps=30.0,
                estimated_round_trip_cost_bps=6.0,
                order_intent_notional_usd=2500.0,
            ),
            state=state,
            timestamp=now,
        )

        self.assertEqual(managed.final_mode, "cash")
        self.assertIn("MAX_CONCURRENT_FUTURES", managed.rejection_reasons)
        self.assertEqual(len(session.closed_trades), 0)
        self.assertIn("ETHUSDT", session.paper_positions)
        self.assertIn("SOLUSDT", session.paper_positions)
        self.assertIn("XRPUSDT", session.paper_positions)
        self.assertIsNone(session.futures_reallocation_cooldown_until)

    def test_futures_reallocation_respects_replacement_cap_when_more_positions_would_be_needed(self) -> None:
        settings = self._focus_settings(futures_top_n=2)
        session = self._build_session(settings=settings)
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        for minutes, symbol, score in (
            (18, "ETHUSDT", 70.0),
            (15, "SOLUSDT", 71.0),
            (12, "ADAUSDT", 72.0),
            (9, "XRPUSDT", 86.0),
        ):
            self._seed_weak_futures_position(
                session,
                symbol=symbol,
                entry_time=now - timedelta(minutes=minutes),
                current_price=90.0 if symbol == "XRPUSDT" else 75.0,
                quantity=10.0,
                entry_predictability_score=89.0 if symbol == "XRPUSDT" else 82.0,
                latest_predictability_score=score,
                entry_net_expected_edge_bps=18.0 if symbol == "XRPUSDT" else 16.0,
                latest_net_expected_edge_bps=15.0 if symbol == "XRPUSDT" else 6.0,
            )
        session.capital_report = {
            "futures_available_balance_usd": 50.0,
            "futures_execution_balance_usd": 1.0,
            "can_trade_futures_any": True,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        managed = session._maybe_reallocate_futures_entry(
            decision=make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=96.0,
                gross_expected_edge_bps=46.0,
                net_expected_edge_bps=34.0,
                estimated_round_trip_cost_bps=6.0,
                order_intent_notional_usd=2500.0,
            ),
            state=state,
            timestamp=now,
        )

        self.assertEqual(managed.final_mode, "cash")
        self.assertIn("MAX_CONCURRENT_FUTURES", managed.rejection_reasons)
        self.assertEqual(len(session.closed_trades), 0)
        self.assertEqual(set(session.paper_positions), {"ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT"})
        self.assertIsNone(session.futures_reallocation_cooldown_until)

    def test_futures_reallocation_cooldown_blocks_repeat_replacement_until_expiry(self) -> None:
        settings = self._focus_settings(futures_top_n=2)
        session = self._build_session(settings=settings)
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        self._seed_weak_futures_position(session, symbol="ETHUSDT", entry_time=now - timedelta(minutes=10))
        session.capital_report = {
            "futures_available_balance_usd": 50.0,
            "futures_execution_balance_usd": 1.0,
            "can_trade_futures_any": True,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                {"symbol": "ADAUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None

        first = session._maybe_reallocate_futures_entry(
            decision=make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=94.0,
                gross_expected_edge_bps=36.0,
                net_expected_edge_bps=24.0,
                estimated_round_trip_cost_bps=6.0,
                order_intent_notional_usd=2500.0,
            ),
            state=state,
            timestamp=now,
        )

        self.assertEqual(first.final_mode, "futures")
        self.assertEqual(len(session.closed_trades), 1)

        self._seed_weak_futures_position(session, symbol="SOLUSDT", entry_time=now - timedelta(minutes=5))
        blocked = session._maybe_reallocate_futures_entry(
            decision=make_decision(
                timestamp=now + timedelta(minutes=5),
                symbol="ADAUSDT",
                predictability_score=95.0,
                gross_expected_edge_bps=38.0,
                net_expected_edge_bps=26.0,
                estimated_round_trip_cost_bps=6.0,
                order_intent_notional_usd=2500.0,
            ),
            state=state,
            timestamp=now + timedelta(minutes=5),
        )

        self.assertEqual(blocked.final_mode, "cash")
        self.assertIn("SOLUSDT", session.paper_positions)
        self.assertEqual(len(session.closed_trades), 1)

        session.capital_report["futures_requirements"].append(
            {"symbol": "XRPUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}
        )
        allowed = session._maybe_reallocate_futures_entry(
            decision=make_decision(
                timestamp=now + timedelta(minutes=10, seconds=1),
                symbol="XRPUSDT",
                predictability_score=96.0,
                gross_expected_edge_bps=39.0,
                net_expected_edge_bps=27.0,
                estimated_round_trip_cost_bps=6.0,
                order_intent_notional_usd=2500.0,
            ),
            state=state,
            timestamp=now + timedelta(minutes=10, seconds=1),
        )

        self.assertEqual(allowed.final_mode, "futures")
        self.assertNotIn("SOLUSDT", session.paper_positions)
        self.assertEqual(len(session.closed_trades), 2)

    def test_futures_reallocation_logs_skip_reason_when_cooldown_blocks_retry(self) -> None:
        settings = self._focus_settings(futures_top_n=2)
        with tempfile.TemporaryDirectory() as tempdir:
            session = self._build_session(settings=settings)
            session.log_store = JsonlLogStore(tempdir)
            now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
            self._seed_weak_futures_position(session, symbol="ETHUSDT", entry_time=now - timedelta(minutes=10))
            session.capital_report = {
                "futures_available_balance_usd": 50.0,
                "futures_execution_balance_usd": 1.0,
                "can_trade_futures_any": True,
                "futures_requirements": [
                    {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                    {"symbol": "ADAUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                ],
            }
            state = session.runtime.dispatcher.store.get("BTCUSDT")
            assert state is not None

            first = session._maybe_reallocate_futures_entry(
                decision=make_decision(
                    timestamp=now,
                    symbol="BTCUSDT",
                    predictability_score=94.0,
                    gross_expected_edge_bps=36.0,
                    net_expected_edge_bps=24.0,
                    estimated_round_trip_cost_bps=6.0,
                    order_intent_notional_usd=2500.0,
                ),
                state=state,
                timestamp=now,
            )
            self.assertEqual(first.final_mode, "futures")

            self._seed_weak_futures_position(session, symbol="SOLUSDT", entry_time=now - timedelta(minutes=5))
            blocked = session._maybe_reallocate_futures_entry(
                decision=make_decision(
                    timestamp=now + timedelta(minutes=5),
                    symbol="ADAUSDT",
                    predictability_score=95.0,
                    gross_expected_edge_bps=38.0,
                    net_expected_edge_bps=26.0,
                    estimated_round_trip_cost_bps=6.0,
                    order_intent_notional_usd=2500.0,
                ),
                state=state,
                timestamp=now + timedelta(minutes=5),
            )

            self.assertEqual(blocked.final_mode, "cash")
            events = session.log_store.read("futures_reallocation")
            self.assertEqual(len(events), 2)
            skip_event = events[-1]
            self.assertEqual(skip_event["status"], "skipped")
            self.assertEqual(skip_event["blocked_reason"], "INSUFFICIENT_EXECUTION_BALANCE")
            self.assertEqual(skip_event["skip_reason"], "REALLOCATION_COOLDOWN_ACTIVE")
            self.assertEqual(skip_event["incoming_symbol"], "ADAUSDT")
            self.assertEqual(skip_event["candidate_strength"]["score"], 95.0)
            self.assertEqual(skip_event["candidate_strength"]["net_edge_bps"], 26.0)
            self.assertEqual(skip_event["cooldown_until"], (now + timedelta(minutes=10)).isoformat())

    def test_futures_reallocation_keeps_exchange_synced_position_protected_in_ordinary_case(self) -> None:
        settings = self._focus_settings(futures_top_n=1)
        with tempfile.TemporaryDirectory() as tempdir:
            session = self._build_session(settings=settings)
            session.log_store = JsonlLogStore(tempdir)
            now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
            self._seed_weak_futures_position(session, symbol="ETHUSDT", entry_time=now - timedelta(minutes=5))
            session.paper_positions["ETHUSDT"].exchange_synced = True
            session.capital_report = {
                "futures_available_balance_usd": 50.0,
                "futures_execution_balance_usd": 1.0,
                "can_trade_futures_any": True,
                "futures_requirements": [
                    {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                ],
            }
            state = session.runtime.dispatcher.store.get("BTCUSDT")
            assert state is not None

            managed = session._maybe_reallocate_futures_entry(
                decision=make_decision(
                    timestamp=now,
                    symbol="BTCUSDT",
                    predictability_score=96.0,
                    gross_expected_edge_bps=36.0,
                    net_expected_edge_bps=24.0,
                    estimated_round_trip_cost_bps=6.0,
                    order_intent_notional_usd=2500.0,
                ),
                state=state,
                timestamp=now,
            )

            self.assertEqual(managed.final_mode, "cash")
            self.assertIn("MAX_CONCURRENT_FUTURES", managed.rejection_reasons)
            self.assertIn("ETHUSDT", session.paper_positions)
            self.assertTrue(session.paper_positions["ETHUSDT"].exchange_synced)
            self.assertEqual(session.closed_trades, [])
            self.assertIsNone(session.futures_reallocation_cooldown_until)

            events = session.log_store.read("futures_reallocation")
            self.assertEqual(len(events), 1)
            skip_event = events[0]
            self.assertEqual(skip_event["status"], "skipped")
            self.assertEqual(skip_event["blocked_reason"], "MAX_CONCURRENT_FUTURES")
            self.assertEqual(skip_event["skip_reason"], "NO_ELIGIBLE_TARGETS")
            self.assertEqual(skip_event["protected_symbols"], ["ETHUSDT"])
            self.assertEqual(skip_event["targets"][0]["symbol"], "ETHUSDT")
            self.assertEqual(skip_event["targets"][0]["protected_reason"], "EXCHANGE_SYNCED_RECENCY_GUARD")
            self.assertEqual(session.log_store.read("closed_trades"), [])

    def test_futures_reallocation_replaces_exchange_synced_position_in_strict_exception_case(self) -> None:
        settings = self._focus_settings(futures_top_n=1)
        with tempfile.TemporaryDirectory() as tempdir:
            session = self._build_session(settings=settings)
            session.log_store = JsonlLogStore(tempdir)
            now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
            self._seed_weak_futures_position(
                session,
                symbol="ETHUSDT",
                entry_time=now - timedelta(minutes=25),
            )
            session.paper_positions["ETHUSDT"].exchange_synced = True
            session.capital_report = {
                "futures_available_balance_usd": 50.0,
                "futures_execution_balance_usd": 1.0,
                "can_trade_futures_any": True,
                "futures_requirements": [
                    {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                ],
            }
            state = session.runtime.dispatcher.store.get("BTCUSDT")
            assert state is not None

            managed = session._maybe_reallocate_futures_entry(
                decision=make_decision(
                    timestamp=now,
                    symbol="BTCUSDT",
                    predictability_score=96.0,
                    gross_expected_edge_bps=36.0,
                    net_expected_edge_bps=24.0,
                    estimated_round_trip_cost_bps=6.0,
                    order_intent_notional_usd=2500.0,
                ),
                state=state,
                timestamp=now,
            )

            self.assertEqual(managed.final_mode, "futures")
            self.assertEqual(managed.order_intent_notional_usd, 2500.0)
            self.assertNotIn("ETHUSDT", session.paper_positions)
            self.assertEqual(len(session.closed_trades), 1)
            self.assertEqual(session.closed_trades[0]["symbol"], "ETHUSDT")
            self.assertEqual(session.closed_trades[0]["exit_reason"], "CAPITAL_REALLOCATION")
            self.assertEqual(session.futures_reallocation_cooldown_until, now + timedelta(minutes=10))

            trade_rows = session.log_store.read("closed_trades")
            self.assertEqual(len(trade_rows), 1)
            self.assertEqual(trade_rows[0]["symbol"], "ETHUSDT")
            self.assertEqual(trade_rows[0]["exit_reason"], "CAPITAL_REALLOCATION")

            events = session.log_store.read("futures_reallocation")
            self.assertEqual(len(events), 1)
            success_event = events[0]
            self.assertEqual(success_event["status"], "executed")
            self.assertEqual(success_event["blocked_reason"], "MAX_CONCURRENT_FUTURES")
            self.assertEqual(success_event["override_reason"], "STRICT_EXCHANGE_SYNCED_EXCEPTION")
            self.assertEqual(success_event["replaced_symbols"], ["ETHUSDT"])
            self.assertEqual(success_event["replaced_count"], 1)
            self.assertEqual(success_event["targets"][0]["exchange_synced"], True)
            self.assertEqual(success_event["targets"][0]["exchange_synced_exception"], True)

    def test_futures_reallocation_allows_small_exchange_synced_loss_under_aggressive_profile(self) -> None:
        settings = replace(
            self._focus_settings(futures_top_n=1),
            portfolio_focus=replace(
                self._focus_settings(futures_top_n=1).portfolio_focus,
                min_score_advantage_to_replace=0.0,
                min_net_edge_advantage_bps=0.0,
                min_incremental_pnl_usd=0.0,
            ),
        )
        with tempfile.TemporaryDirectory() as tempdir:
            session = self._build_session(settings=settings)
            session.log_store = JsonlLogStore(tempdir)
            now = datetime(2026, 3, 8, 12, 30, tzinfo=timezone.utc)
            self._seed_weak_futures_position(
                session,
                symbol="ETHUSDT",
                entry_time=now - timedelta(minutes=25),
                current_price=99.0,
                quantity=0.05,
                entry_net_expected_edge_bps=8.0,
                latest_net_expected_edge_bps=1.0,
            )
            session.paper_positions["ETHUSDT"].exchange_synced = True
            session.capital_report = {
                "futures_available_balance_usd": 1000.0,
                "futures_execution_balance_usd": 1000.0,
                "can_trade_futures_any": True,
                "futures_requirements": [
                    {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                ],
            }
            state = session.runtime.dispatcher.store.get("BTCUSDT")
            assert state is not None

            managed = session._maybe_reallocate_futures_entry(
                decision=make_decision(
                    timestamp=now,
                    symbol="BTCUSDT",
                    predictability_score=96.0,
                    gross_expected_edge_bps=36.0,
                    net_expected_edge_bps=24.0,
                    estimated_round_trip_cost_bps=6.0,
                    order_intent_notional_usd=2500.0,
                ),
                state=state,
                timestamp=now,
            )

            self.assertEqual(managed.final_mode, "futures")
            self.assertNotIn("ETHUSDT", session.paper_positions)

            events = session.log_store.read("futures_reallocation")
            self.assertEqual(len(events), 1)
            success_event = events[0]
            self.assertEqual(success_event["status"], "executed")
            self.assertEqual(success_event["targets"][0]["symbol"], "ETHUSDT")
            self.assertEqual(success_event["targets"][0]["exchange_synced_loss_floor_usd"], 0.01188)
            self.assertEqual(success_event["targets"][0]["exchange_synced_exception"], True)

    def test_async_runner_consumes_payloads(self) -> None:
        session = self._build_session()
        payloads = [
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
                        "x": True,
                    },
                },
            }
        ]
        runner = AsyncLivePaperRunner(FakeWsClient(payloads), session)
        asyncio.run(runner.run())
        self.assertEqual(len(session.decisions), 1)

    def test_live_paper_shell_retries_and_succeeds(self) -> None:
        session = self._build_session()
        payloads = [
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
                        "x": True,
                    },
                },
            }
        ]
        summary_path = ROOT / "tests" / "tmp_shell_summary.json"
        state_path = ROOT / "tests" / "tmp_shell_state.json"
        try:
            shell = LivePaperShell(
                ws_client_factory=FlakyWsFactory(payloads),
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
            self.assertIsNotNone(summary)
            self.assertEqual(len(session.decisions), 1)
            self.assertTrue(summary_path.exists())
            self.assertTrue(state_path.exists())
        finally:
            if summary_path.exists():
                summary_path.unlink()
            if state_path.exists():
                state_path.unlink()

    def test_live_paper_shell_keeps_running_after_missing_market_state_payload(self) -> None:
        session = self._build_session()
        payloads = [
            {
                "stream": "ethusdt@trade",
                "data": {"s": "ETHUSDT", "p": "2100", "q": "0.2", "E": 1772971560000, "m": False},
            },
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
            },
        ]
        summary_path = ROOT / "tests" / "tmp_shell_missing_market_state_summary.json"
        state_path = ROOT / "tests" / "tmp_shell_missing_market_state_state.json"
        try:
            shell = LivePaperShell(
                ws_client_factory=lambda: FakeWsClient(payloads),
                session=session,
                backoff_policy=BackoffPolicy(
                    initial_delay_seconds=0.0,
                    max_delay_seconds=0.0,
                    multiplier=1.0,
                    max_attempts=1,
                ),
                summary_path=summary_path,
                state_path=state_path,
            )
            summary = asyncio.run(shell.run())
            assert summary is not None
            self.assertEqual(len(session.decisions), 1)
            self.assertEqual(summary["self_healing"]["status"], "degraded")
            self.assertEqual(
                summary["self_healing"]["active_guards"]["missing_market_state_symbols"],
                ["ETHUSDT"],
            )
            self.assertTrue(
                any(
                    event["category"] == KNOWN_CATEGORY_MISSING_MARKET_STATE
                    and event["action"] == "skip_payload"
                    for event in summary["self_healing"]["recent_events"]
                )
            )
        finally:
            if summary_path.exists():
                summary_path.unlink()
            if state_path.exists():
                state_path.unlink()

    def test_live_paper_shell_self_heals_stalled_websocket_once_then_recovers(self) -> None:
        session = self._build_session()
        session.self_healing = RuntimeSelfHealing(
            stall_timeout_seconds=1,
            max_stall_restarts_per_window=2,
            stall_restart_window_seconds=600,
        )
        payloads = [
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
                        "x": True,
                    },
                },
            }
        ]
        summary_path = ROOT / "tests" / "tmp_shell_heal_summary.json"
        state_path = ROOT / "tests" / "tmp_shell_heal_state.json"
        try:
            shell = LivePaperShell(
                ws_client_factory=StalledThenHealthyFactory(payloads),
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
            self.assertEqual(len(session.decisions), 1)
            self.assertTrue(
                any(
                    event["category"] == "daemon_stalled" and event["action"] == "restart_websocket"
                    for event in summary["self_healing"]["recent_events"]
                )
            )
        finally:
            if summary_path.exists():
                summary_path.unlink()
            if state_path.exists():
                state_path.unlink()


if __name__ == "__main__":
    unittest.main()
