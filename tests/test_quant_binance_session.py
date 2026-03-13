from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.order_test_adapter import DecisionOrderTestAdapter
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.models import DecisionIntent
from quant_binance.service import PaperTradingService
from quant_binance.session import AsyncLivePaperRunner, BackoffPolicy, LivePaperSession, LivePaperShell
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
        self.assertEqual(session.runtime.loop_stats.closed_decision_kline_count, 1)
        self.assertEqual(session.runtime.loop_stats.emitted_decision_count, 1)

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
        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_PARTIAL_TAKE_PROFIT")
        self.assertTrue(session.live_orders[0]["partial_exit"])
        self.assertEqual(len(session.rest_client.tpsl_orders), 1)
        self.assertTrue(any("LIVE_POSITION_PARTIAL_TAKE_PROFIT" in call.args[0] for call in mock_send.call_args_list))
        session.sync_account()
        self.assertEqual(len(session.live_orders), 1)

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
        session._reconcile_manual_live_closes(previous_live_positions=session.live_positions_snapshot)
        self.assertIn("BTCUSDT", session.paper_positions)

        session.live_positions_snapshot = []
        session.open_orders_snapshot = {"orders": {"entrustedList": [{"symbol": "BTCUSDT", "orderId": "open-1"}]}}
        session._reconcile_manual_live_closes(previous_live_positions=[{"symbol": "BTCUSDT", "holdSide": "long", "total": "0.02", "available": "0.02"}])

        self.assertNotIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.closed_trades[-1]["exit_reason"], "MANUAL_CLOSE_SYNCED")
        self.assertEqual(session.rest_client.cancelled_orders, [("futures", "BTCUSDT", "open-1")])
        cooldown_until = session.manual_symbol_cooldowns["BTCUSDT"]
        remaining = (cooldown_until - datetime.now(timezone.utc)).total_seconds()
        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining, 5 * 60 + 5)
        self.assertFalse(session._is_manual_symbol_cooldown_active("BTCUSDT", cooldown_until + timedelta(seconds=1)))
        self.assertTrue(any("MANUAL_CLOSE_SYNCED" in call.args[0] for call in mock_send.call_args_list))

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


if __name__ == "__main__":
    unittest.main()
