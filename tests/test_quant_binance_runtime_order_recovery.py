from __future__ import annotations

import unittest
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.live_order_adapter import DecisionLiveOrderAdapter, LiveOrderResult
from quant_binance.execution.router import ExecutionRouter
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.models import DecisionIntent
from quant_binance.service import PaperTradingService
from quant_binance.session import AsyncLivePaperRunner, LivePaperSession, LivePaperShell
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class FakeBitgetPrecisionClient:
    exchange_id = "bitget"

    def __init__(self) -> None:
        self.protection_orders: list[dict[str, object]] = []

    def set_futures_leverage(self, *, symbol, leverage):  # type: ignore[no-untyped-def]
        return {"symbol": symbol, "leverage": leverage}

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        return {"status": "SUCCESS", "orderId": "bitget-live-order"}

    def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
        self.protection_orders.append(order_params)
        return {"status": "SUCCESS", "orderId": "bitget-tpsl-order"}

    def place_spot_plan_order(self, *, order_params):  # type: ignore[no-untyped-def]
        raise AssertionError("spot protection orders are not expected in this test")

    def get_exchange_info(self, *, market):  # type: ignore[no-untyped-def]
        return {
            "symbols": [
                {
                    "symbol": "SOLUSDT",
                    "raw": {
                        "pricePlace": "3",
                    },
                }
            ]
        }


class FailingBitgetLiveOrderExecutor:
    def _exchange_id(self) -> str:
        return "bitget"

    def execute_decision(self, *, decision, reference_price):  # type: ignore[no-untyped-def]
        raise RuntimeError('Bitget HTTP 400: {"code":"40762","msg":"The order amount exceeds the balance"}')


class SuccessfulBitgetLiveOrderExecutor:
    def _exchange_id(self) -> str:
        return "bitget"

    def execute_decision(self, *, decision, reference_price):  # type: ignore[no-untyped-def]
        return LiveOrderResult(
            symbol=decision.symbol,
            market="futures",
            side="buy",
            quantity=0.022,
            filled_quantity=0.022,
            fill_ratio=1.0,
            fill_status="filled",
            accepted=True,
            response={"status": "SUCCESS", "orderId": "accepted-1"},
        )


class FakeRestClient:
    exchange_id = "bitget"

    def get_account(self, *, market):  # type: ignore[no-untyped-def]
        return {"executionAvailableBalance": 4.0, "availableBalance": 4.0}

    def get_open_orders(self, *, market):  # type: ignore[no-untyped-def]
        return {"orders": []}

    def get_positions(self):  # type: ignore[no-untyped-def]
        return {"positions": []}

    def build_capital_report(self):  # type: ignore[no-untyped-def]
        raise AssertionError("capital report rebuild should be mocked in this test")


class QuantBinanceRuntimeOrderRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def _build_session(self, *, live_order_executor) -> LivePaperSession:
        now = datetime(2026, 3, 14, 0, 5, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="ETHUSDT",
                top_of_book=TopOfBook(1911.5, 1.0, 1912.0, 1.5, now),
                last_trade_price=1911.8,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=3.0,
                last_update_time=now,
            )
        )
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(store),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: None,
            history_provider=lambda symbol, decision_time: None,
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=FakeRestClient(),
            live_order_executor=live_order_executor,
        )
        session.capital_report = {
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "can_trade_futures_any": True,
            "futures_requirements": [{"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01}],
        }
        return session

    def _decision(self) -> DecisionIntent:
        return DecisionIntent(
            decision_id="recovery-decision",
            decision_hash="recovery-hash",
            snapshot_id="recovery-snapshot",
            config_version="2026-03-14.v1",
            timestamp=datetime(2026, 3, 14, 0, 5, tzinfo=timezone.utc),
            symbol="ETHUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=40.0,
            stop_distance_bps=45.0,
        )

    def test_live_order_adapter_rounds_bitget_protection_prices_to_exchange_scale(self) -> None:
        decision = DecisionIntent(
            decision_id="precision-test",
            decision_hash="precision-hash",
            snapshot_id="precision-snapshot",
            config_version="2026-03-14.v1",
            timestamp=datetime(2026, 3, 14, 0, 5, tzinfo=timezone.utc),
            symbol="SOLUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.7,
            volume_confirmation=0.6,
            liquidity_score=0.5,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=60.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=80.0,
            stop_distance_bps=120.0,
        )
        client = FakeBitgetPrecisionClient()
        adapter = DecisionLiveOrderAdapter(client, self.settings)  # type: ignore[arg-type]
        take_profit, stop_loss = adapter._protection_prices(
            decision=decision,
            reference_price=89.846437,
        )

        result = adapter.execute_decision(decision=decision, reference_price=89.846437)

        self.assertIsNotNone(result)
        expected_stop = format(Decimal(str(stop_loss)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP), ".3f")
        expected_take = format(Decimal(str(take_profit)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP), ".3f")
        self.assertEqual(client.protection_orders[0]["stopLossTriggerPrice"], expected_stop)
        self.assertEqual(client.protection_orders[0]["stopSurplusTriggerPrice"], expected_take)

    def test_session_refreshes_account_state_after_bitget_balance_error(self) -> None:
        session = self._build_session(live_order_executor=FailingBitgetLiveOrderExecutor())
        session._refresh_account_state_after_live_order_activity = Mock()  # type: ignore[method-assign]
        session._apply_paper_trade_management = Mock(return_value=True)  # type: ignore[method-assign]

        state = session.runtime.dispatcher.store.get("ETHUSDT")
        assert state is not None
        session._record_decision(decision=self._decision(), state=state, timestamp=self._decision().timestamp)

        session._refresh_account_state_after_live_order_activity.assert_called_once_with(
            symbol="ETHUSDT",
            timestamp=self._decision().timestamp,
            stage="live_order",
            reason="balance_error",
        )

    def test_session_refreshes_account_state_after_accepted_live_order(self) -> None:
        session = self._build_session(live_order_executor=SuccessfulBitgetLiveOrderExecutor())
        session._refresh_account_state_after_live_order_activity = Mock()  # type: ignore[method-assign]
        session._apply_paper_trade_management = Mock(return_value=True)  # type: ignore[method-assign]

        state = session.runtime.dispatcher.store.get("ETHUSDT")
        assert state is not None
        session._record_decision(decision=self._decision(), state=state, timestamp=self._decision().timestamp)

        session._refresh_account_state_after_live_order_activity.assert_called_once_with(
            symbol="ETHUSDT",
            timestamp=self._decision().timestamp,
            stage="live_order",
            reason="accepted_live_order",
        )

    def test_session_skips_stale_scheduled_decision_backfill_on_restart(self) -> None:
        session = self._build_session(live_order_executor=SuccessfulBitgetLiveOrderExecutor())
        now = datetime(2026, 3, 14, 1, 20, tzinfo=timezone.utc)
        session.last_decision_timestamp = datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc)
        session._run_scheduled_decision_boundary = Mock()  # type: ignore[method-assign]

        session._maybe_run_scheduled_decision_cycle(now)

        session._run_scheduled_decision_boundary.assert_not_called()
        self.assertIsNotNone(session.next_scheduled_decision_at)
        assert session.next_scheduled_decision_at is not None
        self.assertGreaterEqual(
            session.next_scheduled_decision_at,
            session._scheduled_decision_boundary_after(now),
        )

    def test_session_ignores_historical_decision_older_than_live_cutoff(self) -> None:
        session = self._build_session(live_order_executor=SuccessfulBitgetLiveOrderExecutor())
        session.minimum_live_decision_timestamp = datetime(2026, 3, 14, 0, 10, tzinfo=timezone.utc)
        state = session.runtime.dispatcher.store.get("ETHUSDT")
        assert state is not None
        stale_decision = DecisionIntent(
            decision_id="stale-decision",
            decision_hash="stale-hash",
            snapshot_id="stale-snapshot",
            config_version="2026-03-14.v1",
            timestamp=datetime(2026, 3, 14, 0, 5, tzinfo=timezone.utc),
            symbol="ETHUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.82,
            volume_confirmation=0.75,
            liquidity_score=0.84,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=86.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=40.0,
            stop_distance_bps=45.0,
        )

        session._record_decision(decision=stale_decision, state=state, timestamp=stale_decision.timestamp)

        self.assertEqual(session.decisions, [])

    def test_shell_monitor_invokes_scheduled_decision_cycle(self) -> None:
        import asyncio

        class IdleRunner:
            async def run(self, handler):  # type: ignore[no-untyped-def]
                await asyncio.sleep(1.2)

        session = self._build_session(live_order_executor=SuccessfulBitgetLiveOrderExecutor())
        session.self_healing.stall_timeout_seconds = 1
        session._maybe_run_scheduled_decision_cycle = Mock()  # type: ignore[method-assign]
        shell = LivePaperShell(
            ws_client_factory=lambda: None,
            session=session,
        )
        shell.backoff_policy = shell.backoff_policy.__class__(
            initial_delay_seconds=0.0,
            max_delay_seconds=0.0,
            multiplier=1.0,
            max_attempts=1,
        )

        with self.assertRaisesRegex(RuntimeError, "SELF_HEAL_STALL_RESTART"):
            asyncio.run(shell._run_with_monitor(AsyncLivePaperRunner(IdleRunner(), session)))

        self.assertGreaterEqual(session._maybe_run_scheduled_decision_cycle.call_count, 1)
