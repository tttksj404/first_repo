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
from quant_binance.data.state import KlineBar, SymbolMarketState, TopOfBook
from quant_binance.execution.bitget_rest import BitgetRestClient
from quant_binance.execution.order_test_adapter import DecisionOrderTestAdapter
from quant_binance.execution.router import ExecutionRouter
from quant_binance.execution_quality import ExecutionQualityState
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.models import DecisionIntent
from quant_binance.policy.execution import (
    build_execution_intent,
    decision_from_execution_intent,
    is_major_medium_futures_decision,
    is_major_strong_futures_decision,
)
from quant_binance.observability.log_store import JsonlLogStore
from quant_binance.observability.report import build_persisted_policy_state
from quant_binance.service import PaperTradingService
from quant_binance.session import AsyncLivePaperRunner, BackoffPolicy, LivePaperSession, LivePaperShell, PaperPosition
from quant_binance.self_healing import KNOWN_CATEGORY_MISSING_MARKET_STATE, RuntimeSelfHealing
from quant_binance.settings import Settings, SymbolFilterProfileConfig


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
    def test_execution_policy_major_strength_classifier(self) -> None:
        decision = replace(
            make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                final_mode="futures",
                symbol="BTCUSDT",
                side="long",
                predictability_score=86.0,
                liquidity_score=0.9,
                gross_expected_edge_bps=30.0,
                estimated_round_trip_cost_bps=10.0,
                net_expected_edge_bps=20.0,
            ),
            trend_strength=0.9,
            volume_confirmation=0.85,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
        )
        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                max_futures_leverage=30.0,
                target_futures_leverage=30.0,
            ),
        )
        session = self._build_session(settings=settings)
        exposure = session.runtime.paper_service.settings.futures_exposure
        thresholds = session.runtime.paper_service.settings.mode_thresholds
        self.assertTrue(is_major_strong_futures_decision(decision=decision, major_symbols=exposure.major_symbols, exposure=exposure, thresholds=thresholds))
        self.assertFalse(is_major_medium_futures_decision(decision=decision, major_symbols=exposure.major_symbols, exposure=exposure, thresholds=thresholds))

    def test_execution_intent_compiles_back_to_decision(self) -> None:
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        decision = make_decision(timestamp=now, final_mode="spot", side="long", order_intent_notional_usd=432.1)
        intent = build_execution_intent(
            decision=decision,
            execution_symbol="BTCUSDC",
            spot_base_asset="BTC",
            spot_quote_asset="USDC",
            spot_funding_asset="USDC",
            spot_quote_asset_usd_price=1.0,
        )
        compiled = decision_from_execution_intent(intent=intent)
        self.assertEqual(compiled.decision_id, decision.decision_id)
        self.assertEqual(compiled.execution_symbol, "BTCUSDC")
        self.assertEqual(compiled.spot_quote_asset, "USDC")
        self.assertEqual(compiled.order_intent_notional_usd, 432.1)

    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def setUp(self) -> None:
        self._telegram_report_only_patch = patch(
            "quant_binance.session.telegram_report_only_enabled",
            return_value=False,
        )
        self._telegram_report_only_patch.start()

    def tearDown(self) -> None:
        self._telegram_report_only_patch.stop()

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
            decision_interval_seconds=active_settings.decision_engine.decision_interval_seconds,
        )
        return LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=FakeRestClient(),
            order_tester=DecisionOrderTestAdapter(FakeOrderTestClient()),  # type: ignore[arg-type]
            sync_interval_seconds=1,
        )

    def test_schedulable_symbols_follow_configured_universe_priority(self) -> None:
        settings = replace(self.settings, universe=("PEPEUSDT", "DOGEUSDT", "BTCUSDT"))
        session = self._build_session(settings=settings)
        store = session.runtime.dispatcher.store
        btc_state = store.get("BTCUSDT")
        assert btc_state is not None
        store.put(replace(btc_state, symbol="DOGEUSDT"))
        store.put(replace(btc_state, symbol="PEPEUSDT"))
        session.runtime.eligible_symbols = {"BTCUSDT", "DOGEUSDT", "PEPEUSDT"}

        self.assertEqual(session._iter_schedulable_symbols(), ["PEPEUSDT", "DOGEUSDT", "BTCUSDT"])

    def test_single_slot_priority_fallback_runs_universe_order_on_direct_websocket_decision(self) -> None:
        settings = replace(
            self.settings,
            universe=("PEPEUSDT", "DOGEUSDT", "BTCUSDT"),
            portfolio_focus=replace(self.settings.portfolio_focus, enabled=True, futures_top_n=1),
            operational_limits=replace(self.settings.operational_limits, max_concurrent_futures_symbols=1),
        )
        session = self._build_session(settings=settings)
        store = session.runtime.dispatcher.store
        btc_state = store.get("BTCUSDT")
        assert btc_state is not None
        store.put(replace(btc_state, symbol="DOGEUSDT"))
        store.put(replace(btc_state, symbol="PEPEUSDT"))
        session.runtime.eligible_symbols = {"BTCUSDT", "DOGEUSDT", "PEPEUSDT"}
        timestamp = datetime(2026, 4, 22, 4, 15, tzinfo=timezone.utc)
        decision = make_decision(timestamp=timestamp, symbol="DOGEUSDT")
        session.runtime.on_payload = Mock(return_value=decision)
        session.runtime.paper_service.run_cycle = Mock(
            side_effect=lambda state, decision_time, **kwargs: make_decision(
                timestamp=decision_time,
                symbol=state.symbol,
                final_mode="cash",
                side="flat",
                order_intent_notional_usd=0.0,
            )
        )

        session.process_payload({"stream": "dogeusdt@kline_5m", "data": {}}, now=timestamp)

        self.assertEqual([decision.symbol for decision in session.decisions], ["PEPEUSDT", "DOGEUSDT", "BTCUSDT"])
        self.assertGreater(session.next_scheduled_decision_at, timestamp)

    def test_single_slot_priority_fallback_defers_future_direct_websocket_decision(self) -> None:
        settings = replace(
            self.settings,
            universe=("PEPEUSDT", "DOGEUSDT", "BTCUSDT"),
            portfolio_focus=replace(self.settings.portfolio_focus, enabled=True, futures_top_n=1),
            operational_limits=replace(self.settings.operational_limits, max_concurrent_futures_symbols=1),
        )
        session = self._build_session(settings=settings)
        store = session.runtime.dispatcher.store
        btc_state = store.get("BTCUSDT")
        assert btc_state is not None
        store.put(replace(btc_state, symbol="DOGEUSDT"))
        store.put(replace(btc_state, symbol="PEPEUSDT"))
        session.runtime.eligible_symbols = {"BTCUSDT", "DOGEUSDT", "PEPEUSDT"}
        event_time = datetime(2026, 4, 22, 4, 17, tzinfo=timezone.utc)
        future_decision_time = datetime(2026, 4, 22, 4, 20, tzinfo=timezone.utc)
        session.runtime.on_payload = Mock(return_value=make_decision(timestamp=future_decision_time, symbol="DOGEUSDT"))
        session.runtime.paper_service.run_cycle = Mock()

        session.process_payload({"stream": "dogeusdt@kline_5m", "data": {}}, now=event_time)

        self.assertEqual(session.decisions, [])
        session.runtime.paper_service.run_cycle.assert_not_called()
        self.assertEqual(session.next_scheduled_decision_at, future_decision_time)

    def test_single_slot_priority_scheduled_cycle_uses_stale_snapshot_fallback(self) -> None:
        settings = replace(
            self.settings,
            universe=("PEPEUSDT", "DOGEUSDT", "BTCUSDT"),
            portfolio_focus=replace(self.settings.portfolio_focus, enabled=True, futures_top_n=1),
            operational_limits=replace(self.settings.operational_limits, max_concurrent_futures_symbols=1),
        )
        session = self._build_session(settings=settings)
        store = session.runtime.dispatcher.store
        btc_state = store.get("BTCUSDT")
        assert btc_state is not None
        stale_state = replace(
            btc_state,
            last_update_time=datetime(2026, 4, 22, 4, 30, tzinfo=timezone.utc),
            top_of_book=replace(btc_state.top_of_book, updated_at=datetime(2026, 4, 22, 4, 30, tzinfo=timezone.utc)),
        )
        for symbol in ("BTCUSDT", "DOGEUSDT", "PEPEUSDT"):
            store.put(replace(stale_state, symbol=symbol))
        session.runtime.eligible_symbols = {"BTCUSDT", "DOGEUSDT", "PEPEUSDT"}
        decision_time = datetime(2026, 4, 22, 4, 40, tzinfo=timezone.utc)
        session.next_scheduled_decision_at = decision_time
        session.runtime.paper_service.run_cycle = Mock(
            side_effect=lambda state, decision_time, **kwargs: make_decision(
                timestamp=decision_time,
                symbol=state.symbol,
                final_mode="cash",
                side="flat",
                order_intent_notional_usd=0.0,
            )
        )

        session._maybe_run_scheduled_decision_cycle(decision_time)

        self.assertEqual([decision.symbol for decision in session.decisions], ["PEPEUSDT", "DOGEUSDT", "BTCUSDT"])

    def test_scheduled_cycle_corrects_diverged_reference_price_from_top_of_book(self) -> None:
        settings = replace(self.settings, universe=("XRPUSDT",))
        session = self._build_session(settings=settings)
        decision_time = datetime(2026, 4, 22, 5, 5, tzinfo=timezone.utc)
        store = session.runtime.dispatcher.store
        btc_state = store.get("BTCUSDT")
        assert btc_state is not None
        store.put(
            replace(
                btc_state,
                symbol="XRPUSDT",
                last_trade_price=1.4239,
                top_of_book=TopOfBook(1.4452, 1000.0, 1.4453, 1000.0, decision_time),
                last_update_time=decision_time,
            )
        )
        session.runtime.eligible_symbols = {"XRPUSDT"}
        observed_reference_prices: list[float] = []

        def run_cycle(state, decision_time, **kwargs):  # type: ignore[no-untyped-def]
            observed_reference_prices.append(state.last_trade_price)
            return make_decision(
                timestamp=decision_time,
                symbol=state.symbol,
                final_mode="cash",
                side="flat",
                order_intent_notional_usd=0.0,
            )

        session.runtime.paper_service.run_cycle = Mock(side_effect=run_cycle)

        session._run_scheduled_decision_boundary_with_options(
            decision_time,
            allow_stale_snapshot=True,
        )

        self.assertEqual(len(observed_reference_prices), 1)
        self.assertAlmostEqual(observed_reference_prices[0], 1.44525, places=8)
        self.assertEqual(session.reference_price_guard_counts, {"XRPUSDT": 1})
        guard_event = session.reference_price_guard_last_by_symbol["XRPUSDT"]
        self.assertEqual(guard_event["observed_at"], decision_time.isoformat())
        self.assertAlmostEqual(float(guard_event["last_trade_price"]), 1.4239, places=8)
        self.assertAlmostEqual(float(guard_event["top_mid"]), 1.44525, places=8)
        self.assertGreater(float(guard_event["deviation_bps"]), 50.0)

    def test_paper_verify_front_gate_blocks_fee_drag_candidate_before_preflight(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        decision = make_decision(
            timestamp=datetime(2026, 4, 22, 4, 45, tzinfo=timezone.utc),
            net_expected_edge_bps=1.0,
            gross_expected_edge_bps=9.0,
            order_intent_notional_usd=200.0,
        )

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            session._record_decision(decision=decision, state=state, timestamp=decision.timestamp)

        self.assertEqual(session.decisions[-1].final_mode, "cash")
        self.assertEqual(session.decisions[-1].side, "flat")
        self.assertIn("EXPECTED_PROFIT_TOO_SMALL", session.decisions[-1].rejection_reasons)

    def test_auto_convert_skips_spot_dust_below_exchange_minimum_notional(self) -> None:
        class DustSpotRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.order_params_calls: list[dict[str, object]] = []
                self.place_order_calls: list[tuple[str, dict[str, object]]] = []
                self.transfer_calls: list[dict[str, object]] = []

            def get_account(self, *, market: str) -> dict[str, object]:
                if market == "spot":
                    return {
                        "balances": [
                            {"asset": "BTC", "free": "0.000001", "locked": "0"},
                        ]
                    }
                return {
                    "availableBalance": "10.0",
                    "accounts": [
                        {"marginCoin": "USDT", "available": "10.0", "usdtEquity": "10.0"},
                    ],
                }

            def get_book_ticker(self, *, market: str, symbol: str) -> dict[str, object]:
                assert market == "spot"
                assert symbol == "BTCUSDT"
                return {"bidPrice": "85000.0", "askPrice": "85010.0"}

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                self.order_params_calls.append(dict(kwargs))
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.place_order_calls.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "dust-should-not-sell"}

            def transfer_asset(self, **kwargs):  # type: ignore[no-untyped-def]
                self.transfer_calls.append(dict(kwargs))
                return {"status": "SUCCESS"}

        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                max_futures_leverage=30.0,
                target_futures_leverage=30.0,
            ),
        )
        session = self._build_session(settings=settings)
        rest_client = DustSpotRestClient()
        session.rest_client = rest_client
        session.account_snapshot = rest_client.get_account(market="futures")

        session._auto_convert_coin_futures_to_usdt()

        self.assertEqual(rest_client.order_params_calls, [])
        self.assertEqual(rest_client.place_order_calls, [])
        self.assertEqual(rest_client.transfer_calls, [])

    def test_auto_convert_skips_unpriced_spot_dust_instead_of_submitting_live_sell(self) -> None:
        class UnpricedDustSpotRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.order_params_calls: list[dict[str, object]] = []
                self.place_order_calls: list[tuple[str, dict[str, object]]] = []
                self.transfer_calls: list[dict[str, object]] = []

            def get_account(self, *, market: str) -> dict[str, object]:
                if market == "spot":
                    return {
                        "balances": [
                            {"asset": "BTC", "free": "0.000001", "locked": "0"},
                        ]
                    }
                return {
                    "availableBalance": "10.0",
                    "accounts": [
                        {"marginCoin": "USDT", "available": "10.0", "usdtEquity": "10.0"},
                    ],
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                self.order_params_calls.append(dict(kwargs))
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.place_order_calls.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "unpriced-dust-should-not-sell"}

            def transfer_asset(self, **kwargs):  # type: ignore[no-untyped-def]
                self.transfer_calls.append(dict(kwargs))
                return {"status": "SUCCESS"}

        session = self._build_session()
        rest_client = UnpricedDustSpotRestClient()
        session.rest_client = rest_client
        session.account_snapshot = rest_client.get_account(market="futures")

        session._auto_convert_coin_futures_to_usdt()

        self.assertEqual(rest_client.order_params_calls, [])
        self.assertEqual(rest_client.place_order_calls, [])
        self.assertEqual(rest_client.transfer_calls, [])

    def test_auto_convert_uses_capital_report_transferable_usd_for_spot_dust_guard(self) -> None:
        class MispricedDustSpotRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.order_params_calls: list[dict[str, object]] = []
                self.place_order_calls: list[tuple[str, dict[str, object]]] = []
                self.transfer_calls: list[dict[str, object]] = []

            def get_account(self, *, market: str) -> dict[str, object]:
                if market == "spot":
                    return {
                        "balances": [
                            {"asset": "BTC", "free": "0.000001", "locked": "0", "usdValue": "10.0"},
                        ]
                    }
                return {
                    "availableBalance": "10.0",
                    "accounts": [
                        {"marginCoin": "USDT", "available": "10.0", "usdtEquity": "10.0"},
                    ],
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                self.order_params_calls.append(dict(kwargs))
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.place_order_calls.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "mispriced-dust-should-not-sell"}

            def transfer_asset(self, **kwargs):  # type: ignore[no-untyped-def]
                self.transfer_calls.append(dict(kwargs))
                return {"status": "SUCCESS"}

        session = self._build_session()
        rest_client = MispricedDustSpotRestClient()
        session.rest_client = rest_client
        session.capital_report = {
            "capital_transfer_routes": [
                {
                    "source_market": "spot",
                    "target_market": "futures",
                    "asset": "BTC",
                    "source_free_amount": 0.000001,
                    "transferable_usd": 0.084262,
                }
            ]
        }
        session.account_snapshot = rest_client.get_account(market="futures")

        session._auto_convert_coin_futures_to_usdt()

        self.assertEqual(rest_client.order_params_calls, [])
        self.assertEqual(rest_client.place_order_calls, [])
        self.assertEqual(rest_client.transfer_calls, [])

    def test_auto_convert_ignores_misleading_spot_balance_usd_value_when_ticker_shows_dust(self) -> None:
        class MisleadingBalanceRowRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.order_params_calls: list[dict[str, object]] = []
                self.place_order_calls: list[tuple[str, dict[str, object]]] = []
                self.transfer_calls: list[dict[str, object]] = []

            def get_account(self, *, market: str) -> dict[str, object]:
                if market == "spot":
                    return {
                        "balances": [
                            {"asset": "BTC", "free": "0.000001", "locked": "0", "usdValue": "10.0"},
                        ]
                    }
                return {
                    "availableBalance": "10.0",
                    "accounts": [
                        {"marginCoin": "USDT", "available": "10.0", "usdtEquity": "10.0"},
                    ],
                }

            def get_book_ticker(self, *, market: str, symbol: str) -> dict[str, object]:
                assert market == "spot"
                assert symbol == "BTCUSDT"
                return {"bidPrice": "85000.0", "askPrice": "85010.0"}

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                self.order_params_calls.append(dict(kwargs))
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.place_order_calls.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "misleading-balance-row-should-not-sell"}

            def transfer_asset(self, **kwargs):  # type: ignore[no-untyped-def]
                self.transfer_calls.append(dict(kwargs))
                return {"status": "SUCCESS"}

        session = self._build_session()
        rest_client = MisleadingBalanceRowRestClient()
        session.rest_client = rest_client
        session.account_snapshot = rest_client.get_account(market="futures")

        session._auto_convert_coin_futures_to_usdt()

        self.assertEqual(rest_client.order_params_calls, [])
        self.assertEqual(rest_client.place_order_calls, [])
        self.assertEqual(rest_client.transfer_calls, [])

    def test_auto_convert_ignores_misleading_spot_balance_usd_value_when_ticker_has_no_price(self) -> None:
        class EmptyTickerBalanceRowRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.order_params_calls: list[dict[str, object]] = []
                self.place_order_calls: list[tuple[str, dict[str, object]]] = []
                self.transfer_calls: list[dict[str, object]] = []

            def get_account(self, *, market: str) -> dict[str, object]:
                if market == "spot":
                    return {
                        "balances": [
                            {"asset": "BTC", "free": "0.000001", "locked": "0", "usdValue": "10.0"},
                        ]
                    }
                return {
                    "availableBalance": "10.0",
                    "accounts": [
                        {"marginCoin": "USDT", "available": "10.0", "usdtEquity": "10.0"},
                    ],
                }

            def get_book_ticker(self, *, market: str, symbol: str) -> dict[str, object]:
                assert market == "spot"
                assert symbol == "BTCUSDT"
                return {"bidPrice": "0", "askPrice": "0", "raw": {"note": "missing_live_price"}}

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                self.order_params_calls.append(dict(kwargs))
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.place_order_calls.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "empty-ticker-should-not-sell"}

            def transfer_asset(self, **kwargs):  # type: ignore[no-untyped-def]
                self.transfer_calls.append(dict(kwargs))
                return {"status": "SUCCESS"}

        session = self._build_session()
        rest_client = EmptyTickerBalanceRowRestClient()
        session.rest_client = rest_client
        session.account_snapshot = rest_client.get_account(market="futures")

        session._auto_convert_coin_futures_to_usdt()

        self.assertEqual(rest_client.order_params_calls, [])
        self.assertEqual(rest_client.place_order_calls, [])
        self.assertEqual(rest_client.transfer_calls, [])

    def test_major_cross_symbol_alignment_closes_opposite_paper_major_before_new_entry(self) -> None:
        session = self._build_session()
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        session.paper_positions["ETHUSDT"] = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol="ETHUSDT",
            market="futures",
            side="short",
            entry_time=now - timedelta(minutes=20),
            entry_price=2500.0,
            current_price=2450.0,
            quantity_opened=0.5,
            quantity_remaining=0.5,
            stop_distance_bps=500.0,
            active_stop_price=2550.0,
            best_price=2450.0,
            worst_price=2500.0,
            entry_predictability_score=82.0,
            entry_liquidity_score=0.8,
            entry_net_expected_edge_bps=18.0,
            entry_estimated_round_trip_cost_bps=10.0,
            entry_planned_leverage=3,
        )
        closed, changed = session._align_major_cross_symbol_positions(
            decision=make_decision(timestamp=now, symbol="BTCUSDT", side="long", predictability_score=84.0, net_expected_edge_bps=19.0),
            price_map={"BTCUSDT": 50000.0},
            timestamp=now,
        )
        self.assertTrue(changed)
        self.assertEqual(closed, ["ETHUSDT"])
        self.assertNotIn("ETHUSDT", session.paper_positions)

    def test_profitable_major_reversal_starts_confirmation_path(self) -> None:
        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_reversal_confirmation_cycles=3,
                major_reversal_min_holding_minutes=20,
            ),
        )
        session = self._build_session(settings=settings)
        now = datetime(2026, 3, 8, 12, 30, tzinfo=timezone.utc)
        position = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="long",
            entry_time=now - timedelta(minutes=15),
            entry_price=50000.0,
            current_price=50250.0,
            quantity_opened=0.01,
            quantity_remaining=0.01,
            stop_distance_bps=500.0,
            active_stop_price=49750.0,
            best_price=50250.0,
            worst_price=49750.0,
            entry_predictability_score=80.0,
            entry_liquidity_score=0.8,
            entry_net_expected_edge_bps=15.0,
            entry_estimated_round_trip_cost_bps=10.0,
            entry_planned_leverage=3,
        )
        session.paper_positions["BTCUSDT"] = position
        decision = make_decision(
            timestamp=now,
            symbol="BTCUSDT",
            side="short",
            predictability_score=78.0,
            net_expected_edge_bps=16.0,
            estimated_round_trip_cost_bps=10.0,
        )
        state = SymbolMarketState(
            symbol="BTCUSDT",
            top_of_book=TopOfBook(50249.5, 1.0, 50250.5, 1.0, now),
            last_trade_price=50250.0,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=3.0,
            last_update_time=now,
        )
        allow, pyramid = session._apply_paper_trade_management(decision=decision, state=state, timestamp=now)
        self.assertFalse(allow)
        self.assertFalse(pyramid)
        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.paper_positions["BTCUSDT"].exit_confirmation_count, 1)

    def test_force_major_reversal_alignment_does_not_close_underwater_major_position(self) -> None:
        session = self._build_session()
        now = datetime(2026, 3, 8, 12, 30, tzinfo=timezone.utc)
        position = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="long",
            entry_time=now - timedelta(minutes=15),
            entry_price=50000.0,
            current_price=49750.0,
            quantity_opened=0.01,
            quantity_remaining=0.01,
            stop_distance_bps=500.0,
            active_stop_price=49750.0,
            best_price=50100.0,
            worst_price=49750.0,
            entry_predictability_score=80.0,
            entry_liquidity_score=0.8,
            entry_net_expected_edge_bps=15.0,
            entry_estimated_round_trip_cost_bps=10.0,
            entry_planned_leverage=3,
        )
        session.paper_positions["BTCUSDT"] = position
        decision = make_decision(
            timestamp=now,
            symbol="BTCUSDT",
            side="short",
            predictability_score=78.0,
            net_expected_edge_bps=16.0,
            estimated_round_trip_cost_bps=10.0,
        )
        state = SymbolMarketState(
            symbol="BTCUSDT",
            top_of_book=TopOfBook(49899.5, 1.0, 49900.5, 1.0, now),
            last_trade_price=49900.0,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=3.0,
            last_update_time=now,
        )
        allow, pyramid = session._apply_paper_trade_management(decision=decision, state=state, timestamp=now)
        self.assertFalse(allow)
        self.assertFalse(pyramid)
        self.assertIn("BTCUSDT", session.paper_positions)

    def test_cap_live_order_decision_blocks_alt_when_persisted_policy_is_majors_only(self) -> None:
        import tempfile
        session = self._build_session()
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 1000.0,
            "futures_available_balance_usd": 1000.0,
            "futures_requirements": [{"symbol": "SOLUSDT", "min_notional_usd": 5.0, "min_quantity": 0.1}],
        }
        session.live_orders = [{"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 20.0, "realized_edge_bps": 20.0}] * 5
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            session.summary_path = summary_path
            policy_state = {
                "active_policy": {
                    "status": "promote",
                    "adjustments": [{
                        "symbol": "SOLUSDT", "action": "promote", "size_multiplier": 1.1, "leverage_multiplier": 1.1, "entry_threshold_bps": 0.0, "expected_profit_floor_bps": 0.0, "symbol_bias": "majors_only"
                    }]
                }
            }
            summary_path.with_name("policy_state.json").write_text(json.dumps(policy_state), encoding="utf-8")
            decision = make_decision(timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc), symbol="SOLUSDT", final_mode="futures", order_intent_notional_usd=100.0, net_expected_edge_bps=30.0)
            capped = session._cap_live_order_decision(decision, reference_price=100.0)
            self.assertEqual(capped.final_mode, "cash")
            self.assertIn("ACTIVE_POLICY_MAJORS_ONLY", capped.rejection_reasons)

    def test_cap_live_order_decision_blocks_entries_on_executive_rollback(self) -> None:
        import tempfile
        session = self._build_session()
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 1000.0,
            "futures_available_balance_usd": 1000.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        session.live_orders = [{"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 20.0, "realized_edge_bps": 20.0}] * 5
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            session.summary_path = summary_path
            summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "active_policy": {"status": "baseline", "adjustments": []},
                        "executive_operating_verdict": {
                            "verdict": "rollback",
                            "confidence": "high",
                            "reasons": ["EXECUTIVE_ROLLBACK_BY_VALIDATION_FAILURE"],
                        },
                        "live_evidence_rejudge": {
                            "status": "waiting",
                            "effective_verdict": "rollback",
                        },
                    }
                ),
                encoding="utf-8",
            )
            decision = make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                final_mode="futures",
                order_intent_notional_usd=100.0,
                net_expected_edge_bps=30.0,
            )
            capped = session._cap_live_order_decision(decision, reference_price=50000.0)
            self.assertEqual(capped.final_mode, "cash")
            self.assertIn("EXECUTIVE_OPERATING_VERDICT_ROLLBACK", capped.rejection_reasons)
            self.assertIn("LIVE_EVIDENCE_REJUDGE_WAITING", capped.rejection_reasons)

    def test_cap_live_order_decision_blocks_short_entry_in_long_only_turnaround_mode(self) -> None:
        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=True,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 1000.0,
            "futures_available_balance_usd": 1000.0,
            "futures_requirements": [{"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }

        capped = session._cap_live_order_decision(
            make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="ETHUSDT",
                final_mode="futures",
                side="short",
                order_intent_notional_usd=100.0,
                net_expected_edge_bps=30.0,
            ),
            reference_price=2500.0,
        )

        self.assertEqual(capped.final_mode, "cash")
        self.assertEqual(capped.side, "flat")
        self.assertEqual(capped.order_intent_notional_usd, 0.0)
        self.assertIn("LONG_ONLY_TURNAROUND_ENTRY_LONG_ONLY", capped.rejection_reasons)

    def test_paper_verification_relaxes_policy_gates_without_bypassing_long_only(self) -> None:
        import tempfile

        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=True,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 1000.0,
            "futures_available_balance_usd": 1000.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            "os.environ",
            {"QUANT_PAPER_VERIFY_RELAX_POLICY_GATES": "1"},
        ):
            summary_path = Path(tmpdir) / "summary.json"
            session.summary_path = summary_path
            summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "active_policy": {"status": "baseline", "adjustments": []},
                        "executive_operating_verdict": {"verdict": "rollback"},
                        "live_evidence_rejudge": {"status": "blocked", "effective_verdict": "rollback"},
                        "symbol_lifecycle": [
                            {"symbol": "BTCUSDT", "recommended_action": "hold", "target_state": "observe_only"}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            long_decision = make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                final_mode="futures",
                side="long",
                order_intent_notional_usd=100.0,
                net_expected_edge_bps=30.0,
            )
            short_decision = replace(long_decision, side="short", trend_direction=-1)

            capped_long = session._cap_live_order_decision(long_decision, reference_price=50000.0)
            capped_short = session._cap_live_order_decision(short_decision, reference_price=50000.0)

        self.assertEqual(capped_long.final_mode, "futures")
        self.assertNotIn("EXECUTIVE_OPERATING_VERDICT_ROLLBACK", capped_long.rejection_reasons)
        self.assertNotIn("SYMBOL_LIFECYCLE_HOLD", capped_long.rejection_reasons)
        self.assertEqual(capped_short.final_mode, "cash")
        self.assertIn("LONG_ONLY_TURNAROUND_ENTRY_LONG_ONLY", capped_short.rejection_reasons)

    def test_paper_trade_management_uses_capped_entry_when_enabled(self) -> None:
        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=True,
            ),
        )
        session = self._build_session(settings=settings)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_USE_CAPPED_ENTRY": "1"}):
            opened, pyramid = session._apply_paper_trade_management(
                decision=make_decision(
                    timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                    symbol="BTCUSDT",
                    final_mode="futures",
                    side="short",
                    order_intent_notional_usd=100.0,
                    net_expected_edge_bps=30.0,
                ),
                state=state,
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            )

        self.assertFalse(opened)
        self.assertFalse(pyramid)
        self.assertNotIn("BTCUSDT", session.paper_positions)

    def test_cap_live_order_decision_blocks_symbol_lifecycle_hold(self) -> None:
        import tempfile
        session = self._build_session()
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 1000.0,
            "futures_available_balance_usd": 1000.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        session.live_orders = [{"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 20.0, "realized_edge_bps": 20.0}] * 5
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            session.summary_path = summary_path
            summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "active_policy": {"status": "baseline", "adjustments": []},
                        "symbol_lifecycle": [
                            {"symbol": "BTCUSDT", "recommended_action": "hold", "target_state": "observe_only"}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            decision = make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                final_mode="futures",
                order_intent_notional_usd=100.0,
                net_expected_edge_bps=30.0,
            )
            capped = session._cap_live_order_decision(decision, reference_price=50000.0)
            self.assertEqual(capped.final_mode, "cash")
            self.assertIn("SYMBOL_LIFECYCLE_HOLD", capped.rejection_reasons)

    def test_cap_live_order_decision_blocks_bucket_observe_only_symbol(self) -> None:
        import tempfile
        session = self._build_session()
        session.runtime.eligible_symbols = {"BTCUSDT"}
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 1000.0,
            "futures_available_balance_usd": 1000.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        session.live_orders = [{"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 20.0, "realized_edge_bps": 20.0}] * 5
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            session.summary_path = summary_path
            summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "active_policy": {"status": "baseline", "adjustments": []},
                        "policy_evidence_buckets": {
                            "active_policy": {
                                "available": True,
                                "alignment": {"aligned": True, "status": "aligned"},
                                "evidence": {
                                    "policy_context_bucket_symbol_summary": [
                                        {
                                            "symbol": "BTCUSDT",
                                            "recommendation": "observe_only",
                                            "trade_count": 3,
                                        }
                                    ]
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            decision = make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                final_mode="futures",
                order_intent_notional_usd=100.0,
                net_expected_edge_bps=30.0,
            )
            capped = session._cap_live_order_decision(decision, reference_price=50000.0)
            self.assertEqual(capped.final_mode, "cash")
            self.assertIn("POLICY_BUCKET_OBSERVE_ONLY", capped.rejection_reasons)

    def test_cap_live_order_decision_blocks_non_major_when_auto_mode_is_tighter(self) -> None:
        import tempfile
        session = self._build_session()
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 1000.0,
            "futures_available_balance_usd": 1000.0,
            "futures_requirements": [{"symbol": "XRPUSDT", "min_notional_usd": 5.0, "min_quantity": 0.1}],
        }
        session.live_orders = [{"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 20.0, "realized_edge_bps": 20.0}] * 5
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            session.summary_path = summary_path
            summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "active_policy": {"status": "baseline", "adjustments": []},
                        "auto_mode": {
                            "mode": "tighter",
                            "policy_guidance": {"block_non_major_positive": True},
                            "runtime_guidance": {
                                "mode_thresholds": {"futures_score_min_delta": 2.0},
                                "risk": {"per_trade_equity_risk_scale": 0.85},
                                "cash_reserve": {"when_futures_enabled_delta": 0.03},
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            decision = make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="XRPUSDT",
                final_mode="futures",
                predictability_score=90.0,
                order_intent_notional_usd=100.0,
                net_expected_edge_bps=30.0,
            )
            capped = session._cap_live_order_decision(decision, reference_price=1.0)
            self.assertEqual(capped.final_mode, "cash")
            self.assertIn("AUTO_MODE_BLOCK_NON_MAJOR_POSITIVE", capped.rejection_reasons)

    def test_cash_reserve_fraction_uses_conservative_auto_mode_runtime_guidance(self) -> None:
        import tempfile
        session = self._build_session()
        session.capital_report = {"can_trade_futures_any": True}
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            session.summary_path = summary_path
            summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "active_policy": {"status": "baseline", "adjustments": []},
                        "auto_mode": {
                            "mode": "tighter",
                            "runtime_guidance": {"cash_reserve": {"when_futures_enabled_delta": 0.03}},
                        },
                    }
                ),
                encoding="utf-8",
            )
            expected = session.runtime.paper_service.settings.cash_reserve.when_futures_enabled + 0.03
            self.assertAlmostEqual(session._cash_reserve_fraction(), expected, places=6)

    def test_cap_live_order_decision_uses_persisted_policy_to_relax_expected_profit_floor(self) -> None:
        import tempfile
        session = self._build_session(settings=replace(
            self.settings,
            risk=replace(self.settings.risk, min_meaningful_futures_notional_usd=0.0, min_expected_profit_usd_per_trade=6.0),
        ))
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 120.0,
            "futures_available_balance_usd": 120.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        session.live_orders = [{"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 20.0, "realized_edge_bps": 20.0}] * 5
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            session.summary_path = summary_path
            policy_state = {
                "active_policy": {
                    "status": "promote_aggressive",
                    "adjustments": [{
                        "symbol": "BTCUSDT", "action": "aggressive_promote", "size_multiplier": 1.25, "leverage_multiplier": 1.2, "entry_threshold_bps": -1.5, "expected_profit_floor_bps": -500.0
                    }]
                }
            }
            summary_path.with_name("policy_state.json").write_text(json.dumps(policy_state), encoding="utf-8")
            decision = make_decision(timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc), symbol="BTCUSDT", order_intent_notional_usd=100.0, net_expected_edge_bps=100.0)
            capped = session._cap_live_order_decision(decision, reference_price=100.0)
            self.assertEqual(capped.final_mode, "futures")

    def test_cap_live_order_decision_uses_persisted_policy_to_raise_major_entry_floor(self) -> None:
        import tempfile
        session = self._build_session(settings=replace(
            self.settings,
            futures_exposure=replace(self.settings.futures_exposure, major_medium_min_entry_notional_usd=100.0),
        ))
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 1000.0,
            "futures_available_balance_usd": 1000.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        session.live_orders = [{"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 18.0, "realized_edge_bps": 12.0}] * 5
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            session.summary_path = summary_path
            policy_state = {
                "active_policy": {
                    "status": "demote",
                    "adjustments": [{
                        "symbol": "BTCUSDT", "action": "demote", "size_multiplier": 0.75, "leverage_multiplier": 0.75, "entry_threshold_bps": 5000.0, "expected_profit_floor_bps": 0.0
                    }]
                }
            }
            summary_path.with_name("policy_state.json").write_text(json.dumps(policy_state), encoding="utf-8")
            decision = make_decision(timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc), symbol="BTCUSDT", final_mode="futures", order_intent_notional_usd=120.0, predictability_score=90.0, net_expected_edge_bps=30.0)
            capped = session._cap_live_order_decision(decision, reference_price=50000.0)
            self.assertEqual(capped.final_mode, "cash")
            self.assertIn("MIN_MEANINGFUL_NOTIONAL", capped.rejection_reasons)

    def test_cap_live_order_decision_preserves_execution_quality_size_throttle_below_major_entry_floor(self) -> None:
        settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_medium_min_entry_notional_usd=120.0,
                major_strong_min_entry_notional_usd=120.0,
            ),
            risk=replace(
                self.settings.risk,
                min_meaningful_futures_notional_usd=0.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 1000.0,
            "futures_available_balance_usd": 1000.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        state = ExecutionQualityState()
        base = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        for minute in range(4):
            state.record(
                symbol="BTCUSDT",
                outcome="filled",
                fill_ratio=1.0,
                slippage_bps=12.0,
                realized_edge_bps=4.0,
                expected_edge_bps=18.0,
                protection_degraded=True,
                timestamp=base + timedelta(minutes=minute),
                market="futures",
                exchange_id="binance",
            )
        throttled = state.apply_overlay(
            make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                predictability_score=74.0,
                order_intent_notional_usd=140.0,
                net_expected_edge_bps=24.0,
                estimated_round_trip_cost_bps=8.0,
            ),
            exchange_id="binance",
            now=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
        )

        self.assertGreaterEqual(throttled.order_intent_notional_usd, 120.0)
        capped = session._cap_live_order_decision(throttled, reference_price=50000.0)

        self.assertEqual(capped.final_mode, "futures")
        self.assertGreaterEqual(capped.order_intent_notional_usd, 120.0)
        self.assertNotIn("MIN_MEANINGFUL_NOTIONAL", capped.rejection_reasons)

    def test_policy_rollout_phase_scales_runtime_application_before_five_live_orders(self) -> None:
        import tempfile
        session = self._build_session(
            settings=replace(
                self.settings,
                risk=replace(self.settings.risk, min_expected_profit_usd_per_trade=6.0),
            )
        )
        session.live_orders = [
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 14.0, "realized_edge_bps": 14.0},
        ]
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        decision = make_decision(timestamp=now, symbol="BTCUSDT", order_intent_notional_usd=100.0, net_expected_edge_bps=100.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            session.summary_path = summary_path
            policy_state = {
                "rollout_status": "micro_live_pending",
                "rollout_progression": {"execution_phase": "partial"},
                "active_policy": {
                    "status": "promote",
                    "adjustments": [
                        {
                            "symbol": "BTCUSDT",
                            "action": "promote",
                            "size_multiplier": 1.6,
                            "leverage_multiplier": 1.3,
                            "entry_threshold_bps": -2.0,
                            "expected_profit_floor_bps": -200.0,
                        }
                    ],
                },
            }
            summary_path.with_name("policy_state.json").write_text(json.dumps(policy_state), encoding="utf-8")
            partial_corrected = session._apply_operational_self_correction(decision)
            self.assertAlmostEqual(session._policy_multiplier_for_decision(decision), 1.21, places=6)
            self.assertAlmostEqual(session._policy_leverage_multiplier_for_decision(decision), 1.105, places=6)
            self.assertAlmostEqual(session._min_expected_profit_usd_threshold(decision), 5.3, places=6)
            self.assertAlmostEqual(partial_corrected.order_intent_notional_usd, 121.0, places=6)
            self.assertIn("ACTIVE_POLICY_PHASE_PARTIAL", partial_corrected.size_boost_reasons)

            policy_state["rollout_progression"]["execution_phase"] = "full"
            summary_path.with_name("policy_state.json").write_text(json.dumps(policy_state), encoding="utf-8")
            full_corrected = session._apply_operational_self_correction(decision)
            self.assertAlmostEqual(session._policy_multiplier_for_decision(decision), 1.6, places=6)
            self.assertAlmostEqual(session._policy_leverage_multiplier_for_decision(decision), 1.3, places=6)
            self.assertAlmostEqual(session._min_expected_profit_usd_threshold(decision), 4.0, places=6)
            self.assertAlmostEqual(full_corrected.order_intent_notional_usd, 160.0, places=6)
            self.assertIn("ACTIVE_POLICY_PHASE_FULL", full_corrected.size_boost_reasons)
            self.assertGreater(full_corrected.order_intent_notional_usd, partial_corrected.order_intent_notional_usd)

    def test_staged_rollout_uses_candidate_policy_for_partial_runtime_application(self) -> None:
        session = self._build_session()
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        decision = make_decision(timestamp=now, symbol="BTCUSDT", order_intent_notional_usd=100.0, net_expected_edge_bps=100.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            session.summary_path = summary_path
            summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "status": "staged_rollout",
                        "rollout_status": "micro_live_pending",
                        "rollout_progression": {"execution_phase": "partial"},
                        "active_policy": {"status": "baseline", "adjustments": []},
                        "candidate_policy": {
                            "adjustments": [
                                {
                                    "symbol": "BTCUSDT",
                                    "action": "promote",
                                    "size_multiplier": 1.2,
                                    "leverage_multiplier": 1.2,
                                    "entry_threshold_bps": -10.0,
                                    "expected_profit_floor_bps": -100.0,
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            adjustment = session._policy_adjustment_for_decision(decision)
            self.assertEqual(adjustment["rollout_adjustment_source"], "candidate_policy")
            self.assertEqual(adjustment["rollout_execution_phase"], "partial")
            self.assertAlmostEqual(session._policy_multiplier_for_decision(decision), 1.07, places=6)
            self.assertAlmostEqual(session._policy_leverage_multiplier_for_decision(decision), 1.07, places=6)
            self.assertAlmostEqual(session._policy_entry_floor_adjustment_bps(decision), -3.5, places=6)

    def test_non_staged_runtime_context_does_not_apply_candidate_policy(self) -> None:
        session = self._build_session()
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        decision = make_decision(timestamp=now, symbol="BTCUSDT", order_intent_notional_usd=100.0, net_expected_edge_bps=100.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "summary.json"
            session.summary_path = summary_path
            summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "status": "kept",
                        "rollout_status": "micro_live_pending",
                        "rollout_progression": {"execution_phase": "partial"},
                        "active_policy": {"status": "baseline", "adjustments": []},
                        "candidate_policy": {
                            "adjustments": [
                                {
                                    "symbol": "BTCUSDT",
                                    "action": "promote",
                                    "size_multiplier": 1.2,
                                    "leverage_multiplier": 1.2,
                                    "entry_threshold_bps": -10.0,
                                    "expected_profit_floor_bps": -100.0,
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(session._policy_adjustment_for_decision(decision), {})
            self.assertEqual(session._policy_multiplier_for_decision(decision), 1.0)

    def test_cap_live_order_decision_scales_size_on_operational_hold(self) -> None:
        session = self._build_session()
        session.capital_report = {
            "futures_execution_balance_usd": 5000.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        session.live_orders = [
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.9, "expected_net_edge_bps": 18.0, "realized_edge_bps": 10.8},
            {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.9, "expected_net_edge_bps": 16.0, "realized_edge_bps": 9.6},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.9, "expected_net_edge_bps": 17.0, "realized_edge_bps": 10.2},
            {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.9, "expected_net_edge_bps": 15.0, "realized_edge_bps": 9.0},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.9, "expected_net_edge_bps": 14.0, "realized_edge_bps": 8.4},
        ]
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        capped = session._cap_live_order_decision(make_decision(timestamp=now, order_intent_notional_usd=1000.0), reference_price=50000.0)
        self.assertEqual(capped.final_mode, "futures")
        self.assertAlmostEqual(capped.order_intent_notional_usd, 500.0, places=6)
        self.assertIn("OPERATIONAL_HOLD_SCALE", capped.size_boost_reasons)

    def test_cap_live_order_decision_scales_up_on_operational_aggressive_pass(self) -> None:
        session = self._build_session()
        session.capital_report = {
            "futures_execution_balance_usd": 10000.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        session.live_orders = [
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 15.0, "realized_edge_bps": 15.0},
            {"symbol": "ETHUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 16.0, "realized_edge_bps": 16.0},
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 17.0, "realized_edge_bps": 17.0},
            {"symbol": "ETHUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 18.0, "realized_edge_bps": 18.0},
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 19.0, "realized_edge_bps": 19.0},
            {"symbol": "ETHUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 20.0, "realized_edge_bps": 20.0},
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 21.0, "realized_edge_bps": 21.0},
            {"symbol": "ETHUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 22.0, "realized_edge_bps": 22.0},
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 23.0, "realized_edge_bps": 23.0},
            {"symbol": "ETHUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 24.0, "realized_edge_bps": 24.0},
        ]
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        capped = session._cap_live_order_decision(make_decision(timestamp=now, symbol="BTCUSDT", order_intent_notional_usd=1000.0), reference_price=50000.0)
        self.assertEqual(capped.final_mode, "futures")
        self.assertAlmostEqual(capped.order_intent_notional_usd, 1300.0, places=6)
        self.assertIn("OPERATIONAL_AGGRESSIVE_PASS_SCALE", capped.size_boost_reasons)

    def test_high_conviction_strong_long_uses_target_margin_fraction(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=0.9,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                strong_score_buffer=18.0,
                strong_trend_strength_min=0.64,
                strong_volume_confirmation_min=0.55,
                strong_liquidity_min=0.3,
                strong_volatility_penalty_max=1.0,
                strong_overheat_penalty_max=0.8,
                strong_edge_to_cost_multiple_min=1.2,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)

        capped = session._cap_live_order_decision(
            make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=82.0,
                gross_expected_edge_bps=30.0,
                net_expected_edge_bps=18.0,
                estimated_round_trip_cost_bps=10.0,
                order_intent_notional_usd=120.0,
            ),
            reference_price=50000.0,
        )

        self.assertEqual(capped.final_mode, "futures")
        self.assertAlmostEqual(capped.order_intent_notional_usd, 1282.5, places=6)
        self.assertIn("HIGH_CONVICTION_A_PLUS_SIZE", capped.size_boost_reasons)

    def test_high_conviction_strong_long_can_use_full_execution_headroom(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=1.0,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                strong_score_buffer=18.0,
                strong_trend_strength_min=0.64,
                strong_volume_confirmation_min=0.55,
                strong_liquidity_min=0.3,
                strong_volatility_penalty_max=1.0,
                strong_overheat_penalty_max=0.8,
                strong_edge_to_cost_multiple_min=1.2,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)

        capped = session._cap_live_order_decision(
            make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=82.0,
                gross_expected_edge_bps=30.0,
                net_expected_edge_bps=18.0,
                estimated_round_trip_cost_bps=10.0,
                order_intent_notional_usd=120.0,
            ),
            reference_price=50000.0,
        )

        self.assertEqual(capped.final_mode, "futures")
        self.assertAlmostEqual(capped.order_intent_notional_usd, 1425.0, places=6)
        self.assertIn("HIGH_CONVICTION_A_PLUS_SIZE", capped.size_boost_reasons)

    def test_high_conviction_strong_long_caps_existing_oversized_intent_to_full_headroom(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=1.0,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                strong_score_buffer=18.0,
                strong_trend_strength_min=0.64,
                strong_volume_confirmation_min=0.55,
                strong_liquidity_min=0.3,
                strong_volatility_penalty_max=1.0,
                strong_overheat_penalty_max=0.8,
                strong_edge_to_cost_multiple_min=1.2,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)

        capped = session._cap_live_order_decision(
            make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=82.0,
                gross_expected_edge_bps=30.0,
                net_expected_edge_bps=18.0,
                estimated_round_trip_cost_bps=10.0,
                order_intent_notional_usd=1500.0,
            ),
            reference_price=50000.0,
        )

        self.assertEqual(capped.final_mode, "futures")
        self.assertAlmostEqual(capped.order_intent_notional_usd, 1425.0, places=6)
        self.assertIn("HIGH_CONVICTION_A_PLUS_SIZE", capped.size_boost_reasons)

    def test_high_conviction_medium_long_caps_existing_oversized_intent_to_medium_headroom(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=1.0,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                pyramid_min_predictability_score=68.0,
                pyramid_min_trend_strength=0.55,
                pyramid_min_volume_confirmation=0.45,
                pyramid_min_net_edge_bps=32.0,
                soft_liquidity_floor=0.28,
                min_entry_net_edge_bps=0.9,
                priority_edge_to_cost_multiple_min=1.0,
                strong_score_buffer=18.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)

        capped = session._cap_live_order_decision(
            replace(
                make_decision(
                    timestamp=now,
                    symbol="BTCUSDT",
                    predictability_score=68.5,
                    gross_expected_edge_bps=44.0,
                    net_expected_edge_bps=34.0,
                    estimated_round_trip_cost_bps=10.0,
                    order_intent_notional_usd=1500.0,
                ),
                trend_strength=0.55,
                volume_confirmation=0.45,
                liquidity_score=0.5,
            ),
            reference_price=50000.0,
        )

        self.assertEqual(capped.final_mode, "futures")
        self.assertAlmostEqual(capped.order_intent_notional_usd, 498.75, places=6)
        self.assertIn("HIGH_CONVICTION_MEDIUM_SIZE", capped.size_boost_reasons)

    def test_high_conviction_blocks_thin_medium_long_like_reversal_loss_case(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("ETHUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=1.0,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                pyramid_min_predictability_score=68.0,
                pyramid_min_trend_strength=0.55,
                pyramid_min_volume_confirmation=0.45,
                pyramid_min_net_edge_bps=32.0,
                soft_liquidity_floor=0.28,
                min_entry_net_edge_bps=0.9,
                priority_edge_to_cost_multiple_min=1.0,
                strong_score_buffer=18.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01}],
        }
        now = datetime(2026, 4, 21, 2, 15, tzinfo=timezone.utc)

        capped = session._cap_live_order_decision(
            replace(
                make_decision(
                    timestamp=now,
                    symbol="ETHUSDT",
                    predictability_score=68.817875,
                    gross_expected_edge_bps=35.4,
                    net_expected_edge_bps=29.34,
                    estimated_round_trip_cost_bps=6.06,
                    order_intent_notional_usd=1500.0,
                ),
                trend_strength=0.55,
                volume_confirmation=0.45,
                liquidity_score=0.779,
            ),
            reference_price=2310.18,
        )

        self.assertEqual(capped.final_mode, "cash")
        self.assertEqual(capped.side, "flat")
        self.assertEqual(capped.order_intent_notional_usd, 0.0)
        self.assertIn("HIGH_CONVICTION_A_PLUS_REQUIRED", capped.rejection_reasons)
        self.assertNotIn("HIGH_CONVICTION_MEDIUM_SIZE", capped.size_boost_reasons)

    def test_high_conviction_blocks_thin_a_plus_long_like_pepe_fee_drag_loss_case(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("PEPEUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=1.0,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                pyramid_min_predictability_score=68.0,
                pyramid_min_trend_strength=0.55,
                pyramid_min_volume_confirmation=0.45,
                pyramid_min_net_edge_bps=32.0,
                soft_liquidity_floor=0.28,
                min_entry_net_edge_bps=0.9,
                priority_edge_to_cost_multiple_min=1.0,
                strong_score_buffer=18.0,
                strong_trend_strength_min=0.64,
                strong_volume_confirmation_min=0.55,
                strong_liquidity_min=0.3,
                strong_volatility_penalty_max=1.0,
                strong_overheat_penalty_max=0.8,
                strong_edge_to_cost_multiple_min=1.2,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "PEPEUSDT", "min_notional_usd": 5.0, "min_quantity": 1000.0}],
        }
        now = datetime(2026, 4, 21, 4, 5, tzinfo=timezone.utc)

        capped = session._cap_live_order_decision(
            replace(
                make_decision(
                    timestamp=now,
                    symbol="PEPEUSDT",
                    predictability_score=70.779415,
                    gross_expected_edge_bps=34.194806,
                    net_expected_edge_bps=26.014806,
                    estimated_round_trip_cost_bps=8.18,
                    order_intent_notional_usd=1500.0,
                ),
                trend_strength=0.644223,
                volume_confirmation=0.68032,
                liquidity_score=0.573576,
                volatility_penalty=0.537631,
                overheat_penalty=0.286298,
            ),
            reference_price=0.000004,
        )

        self.assertEqual(capped.final_mode, "cash")
        self.assertEqual(capped.side, "flat")
        self.assertEqual(capped.order_intent_notional_usd, 0.0)
        self.assertIn("HIGH_CONVICTION_A_PLUS_REQUIRED", capped.rejection_reasons)
        self.assertNotIn("HIGH_CONVICTION_A_PLUS_SIZE", capped.size_boost_reasons)

    def test_high_conviction_medium_long_allows_lower_score_when_edge_is_clear(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("ETHUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=1.0,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                pyramid_min_predictability_score=68.0,
                pyramid_min_trend_strength=0.55,
                pyramid_min_volume_confirmation=0.45,
                pyramid_min_net_edge_bps=32.0,
                soft_liquidity_floor=0.28,
                min_entry_net_edge_bps=0.9,
                priority_edge_to_cost_multiple_min=1.0,
                strong_score_buffer=18.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01}],
        }
        now = datetime(2026, 4, 21, 2, 15, tzinfo=timezone.utc)

        capped = session._cap_live_order_decision(
            replace(
                make_decision(
                    timestamp=now,
                    symbol="ETHUSDT",
                    predictability_score=68.5,
                    gross_expected_edge_bps=42.0,
                    net_expected_edge_bps=33.0,
                    estimated_round_trip_cost_bps=7.5,
                    order_intent_notional_usd=1500.0,
                ),
                trend_strength=0.56,
                volume_confirmation=0.46,
                liquidity_score=0.5,
            ),
            reference_price=2310.18,
        )

        self.assertEqual(capped.final_mode, "futures")
        self.assertAlmostEqual(capped.order_intent_notional_usd, 498.75, places=6)
        self.assertIn("HIGH_CONVICTION_MEDIUM_SIZE", capped.size_boost_reasons)

    def test_high_conviction_blocks_medium_long_below_edge_floor_like_sol_loss_case(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("SOLUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=1.0,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                pyramid_min_predictability_score=68.0,
                pyramid_min_trend_strength=0.55,
                pyramid_min_volume_confirmation=0.45,
                pyramid_min_net_edge_bps=32.0,
                soft_liquidity_floor=0.28,
                min_entry_net_edge_bps=0.9,
                priority_edge_to_cost_multiple_min=1.0,
                strong_score_buffer=18.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "SOLUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01}],
        }
        now = datetime(2026, 4, 21, 5, 14, tzinfo=timezone.utc)

        capped = session._cap_live_order_decision(
            replace(
                make_decision(
                    timestamp=now,
                    symbol="SOLUSDT",
                    predictability_score=75.60496,
                    gross_expected_edge_bps=40.17,
                    net_expected_edge_bps=30.82,
                    estimated_round_trip_cost_bps=9.35,
                    order_intent_notional_usd=1500.0,
                ),
                trend_strength=0.58,
                volume_confirmation=0.46,
                liquidity_score=0.5829,
            ),
            reference_price=85.634,
        )

        self.assertEqual(capped.final_mode, "cash")
        self.assertEqual(capped.side, "flat")
        self.assertEqual(capped.order_intent_notional_usd, 0.0)
        self.assertIn("HIGH_CONVICTION_A_PLUS_REQUIRED", capped.rejection_reasons)
        self.assertNotIn("HIGH_CONVICTION_MEDIUM_SIZE", capped.size_boost_reasons)

    def test_high_conviction_blocks_stale_full_size_long_like_probe32_flicker_case(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("ETHUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=1.0,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                high_conviction_max_decision_age_seconds=75,
                pyramid_min_net_edge_bps=32.0,
                strong_score_buffer=18.0,
                strong_trend_strength_min=0.64,
                strong_volume_confirmation_min=0.55,
                strong_liquidity_min=0.3,
                strong_volatility_penalty_max=1.0,
                strong_overheat_penalty_max=0.8,
                strong_edge_to_cost_multiple_min=1.2,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01}],
        }
        decision_time = datetime(2026, 4, 21, 5, 31, tzinfo=timezone.utc)

        capped = session._cap_live_order_decision(
            replace(
                make_decision(
                    timestamp=decision_time,
                    symbol="ETHUSDT",
                    predictability_score=77.971222,
                    gross_expected_edge_bps=43.19,
                    net_expected_edge_bps=36.4,
                    estimated_round_trip_cost_bps=6.79,
                    order_intent_notional_usd=1500.0,
                ),
                trend_strength=0.65,
                volume_confirmation=0.56,
                liquidity_score=0.8529,
            ),
            reference_price=2317.96,
            submission_time=decision_time + timedelta(seconds=96),
        )

        self.assertEqual(capped.final_mode, "cash")
        self.assertEqual(capped.side, "flat")
        self.assertEqual(capped.order_intent_notional_usd, 0.0)
        self.assertIn("HIGH_CONVICTION_STALE_DECISION", capped.rejection_reasons)
        self.assertNotIn("HIGH_CONVICTION_A_PLUS_SIZE", capped.size_boost_reasons)

    def test_high_conviction_blocks_newer_weak_same_symbol_signal_before_submission(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("ETHUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=1.0,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                high_conviction_recent_long_confirmations=1,
                high_conviction_max_decision_age_seconds=75,
                high_conviction_recent_weak_block_enabled=True,
                high_conviction_recent_weak_max_age_seconds=180,
                pyramid_min_net_edge_bps=32.0,
                strong_score_buffer=18.0,
                strong_trend_strength_min=0.64,
                strong_volume_confirmation_min=0.55,
                strong_liquidity_min=0.3,
                strong_volatility_penalty_max=1.0,
                strong_overheat_penalty_max=0.8,
                strong_edge_to_cost_multiple_min=1.2,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01}],
        }
        decision_time = datetime(2026, 4, 21, 5, 31, tzinfo=timezone.utc)
        session.decisions.append(
            replace(
                make_decision(
                    timestamp=decision_time + timedelta(seconds=70),
                    symbol="ETHUSDT",
                    final_mode="cash",
                    side="flat",
                    predictability_score=56.868223,
                    gross_expected_edge_bps=-12.0,
                    net_expected_edge_bps=-20.13,
                    estimated_round_trip_cost_bps=6.79,
                    order_intent_notional_usd=0.0,
                ),
                trend_direction=-1,
                trend_strength=0.21,
                volume_confirmation=0.18,
                rejection_reasons=(
                    "DIRECTION_CONFLICT",
                    "EDGE_BELOW_COST",
                    "EDGE_TOO_THIN",
                    "LIQUIDITY_TOO_WEAK",
                    "SCORE_TOO_LOW",
                ),
            )
        )

        capped = session._cap_live_order_decision(
            replace(
                make_decision(
                    timestamp=decision_time,
                    symbol="ETHUSDT",
                    predictability_score=77.971222,
                    gross_expected_edge_bps=43.19,
                    net_expected_edge_bps=36.4,
                    estimated_round_trip_cost_bps=6.79,
                    order_intent_notional_usd=1500.0,
                ),
                trend_strength=0.65,
                volume_confirmation=0.56,
                liquidity_score=0.8529,
            ),
            reference_price=2317.96,
            submission_time=decision_time + timedelta(seconds=74),
        )

        self.assertEqual(capped.final_mode, "cash")
        self.assertEqual(capped.side, "flat")
        self.assertEqual(capped.order_intent_notional_usd, 0.0)
        self.assertIn("HIGH_CONVICTION_RECENT_WEAK_SIGNAL", capped.rejection_reasons)
        self.assertNotIn("HIGH_CONVICTION_A_PLUS_SIZE", capped.size_boost_reasons)

    def test_high_conviction_blocks_non_medium_long(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=0.9,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                strong_score_buffer=18.0,
                pyramid_min_predictability_score=60.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)

        capped = session._cap_live_order_decision(
            make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=55.0,
                order_intent_notional_usd=120.0,
            ),
            reference_price=50000.0,
        )

        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("HIGH_CONVICTION_A_PLUS_REQUIRED", capped.rejection_reasons)

    def test_high_conviction_requires_recent_same_symbol_long_confirmations(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=0.9,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                high_conviction_recent_long_confirmations=2,
                high_conviction_recent_max_age_minutes=6,
                high_conviction_recent_min_trend_strength=0.5,
                high_conviction_recent_min_volume_confirmation=0.4,
                high_conviction_recent_min_liquidity=0.3,
                high_conviction_recent_max_volatility_penalty=0.85,
                high_conviction_recent_max_overheat_penalty=0.65,
                high_conviction_recent_min_edge_to_cost_multiple=1.15,
                strong_score_buffer=18.0,
                strong_trend_strength_min=0.64,
                strong_volume_confirmation_min=0.55,
                strong_liquidity_min=0.3,
                strong_volatility_penalty_max=1.0,
                strong_overheat_penalty_max=0.8,
                strong_edge_to_cost_multiple_min=1.2,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        session.decisions.extend(
            (
                make_decision(timestamp=now - timedelta(minutes=1), symbol="BTCUSDT", predictability_score=82.0),
            )
        )

        capped = session._cap_live_order_decision(
            make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=82.0,
                gross_expected_edge_bps=30.0,
                net_expected_edge_bps=18.0,
                estimated_round_trip_cost_bps=10.0,
                order_intent_notional_usd=120.0,
            ),
            reference_price=50000.0,
        )

        self.assertEqual(capped.final_mode, "futures")
        self.assertAlmostEqual(capped.order_intent_notional_usd, 1282.5, places=6)
        self.assertIn("HIGH_CONVICTION_A_PLUS_SIZE", capped.size_boost_reasons)

    def test_high_conviction_blocks_when_recent_same_symbol_trend_weakens(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=0.9,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                high_conviction_recent_long_confirmations=2,
                high_conviction_recent_max_age_minutes=6,
                high_conviction_recent_min_trend_strength=0.5,
                high_conviction_recent_min_volume_confirmation=0.4,
                high_conviction_recent_min_liquidity=0.3,
                high_conviction_recent_max_volatility_penalty=0.85,
                high_conviction_recent_max_overheat_penalty=0.65,
                high_conviction_recent_min_edge_to_cost_multiple=1.15,
                strong_score_buffer=18.0,
                strong_trend_strength_min=0.64,
                strong_volume_confirmation_min=0.55,
                strong_liquidity_min=0.3,
                strong_volatility_penalty_max=1.0,
                strong_overheat_penalty_max=0.8,
                strong_edge_to_cost_multiple_min=1.2,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        session.decisions.extend(
            (
                replace(
                    make_decision(timestamp=now - timedelta(minutes=1), symbol="BTCUSDT", predictability_score=82.0),
                    trend_strength=0.3,
                ),
            )
        )

        capped = session._cap_live_order_decision(
            make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=82.0,
                gross_expected_edge_bps=30.0,
                net_expected_edge_bps=18.0,
                estimated_round_trip_cost_bps=10.0,
                order_intent_notional_usd=120.0,
            ),
            reference_price=50000.0,
        )

        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("HIGH_CONVICTION_RECENT_LONG_CONFIRMATION_REQUIRED", capped.rejection_reasons)

    def test_high_conviction_blocks_when_recent_same_symbol_short_signal_was_seen(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=0.9,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                high_conviction_recent_long_confirmations=2,
                high_conviction_recent_max_age_minutes=6,
                high_conviction_recent_min_trend_strength=0.5,
                high_conviction_recent_min_volume_confirmation=0.4,
                high_conviction_recent_min_liquidity=0.3,
                high_conviction_recent_max_volatility_penalty=0.85,
                high_conviction_recent_max_overheat_penalty=0.65,
                high_conviction_recent_min_edge_to_cost_multiple=1.15,
                high_conviction_recent_opposite_block_enabled=True,
                high_conviction_recent_opposite_max_age_minutes=6,
                strong_score_buffer=18.0,
                strong_trend_strength_min=0.64,
                strong_volume_confirmation_min=0.55,
                strong_liquidity_min=0.3,
                strong_volatility_penalty_max=1.0,
                strong_overheat_penalty_max=0.8,
                strong_edge_to_cost_multiple_min=1.2,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        session.decisions.extend(
            (
                make_decision(timestamp=now - timedelta(minutes=2), symbol="BTCUSDT", side="short"),
                make_decision(timestamp=now - timedelta(minutes=1), symbol="BTCUSDT", predictability_score=82.0),
            )
        )

        capped = session._cap_live_order_decision(
            make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=82.0,
                gross_expected_edge_bps=30.0,
                net_expected_edge_bps=18.0,
                estimated_round_trip_cost_bps=10.0,
                order_intent_notional_usd=120.0,
            ),
            reference_price=50000.0,
        )

        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("HIGH_CONVICTION_RECENT_LONG_CONFIRMATION_REQUIRED", capped.rejection_reasons)

    def test_high_conviction_reversal_unlock_allows_clean_longs_after_recent_short(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=0.9,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                high_conviction_recent_long_confirmations=2,
                high_conviction_recent_max_age_minutes=6,
                high_conviction_recent_min_trend_strength=0.5,
                high_conviction_recent_min_volume_confirmation=0.4,
                high_conviction_recent_min_liquidity=0.3,
                high_conviction_recent_max_volatility_penalty=0.85,
                high_conviction_recent_max_overheat_penalty=0.65,
                high_conviction_recent_min_edge_to_cost_multiple=1.15,
                high_conviction_recent_opposite_block_enabled=True,
                high_conviction_recent_opposite_max_age_minutes=6,
                high_conviction_recent_reversal_unlock_enabled=True,
                high_conviction_recent_reversal_unlock_confirmations=3,
                strong_score_buffer=18.0,
                strong_trend_strength_min=0.64,
                strong_volume_confirmation_min=0.55,
                strong_liquidity_min=0.3,
                strong_volatility_penalty_max=1.0,
                strong_overheat_penalty_max=0.8,
                strong_edge_to_cost_multiple_min=1.2,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        session.decisions.extend(
            (
                make_decision(timestamp=now - timedelta(minutes=4), symbol="BTCUSDT", side="short"),
                make_decision(timestamp=now - timedelta(minutes=2), symbol="BTCUSDT", predictability_score=82.0),
                make_decision(timestamp=now - timedelta(minutes=1), symbol="BTCUSDT", predictability_score=83.0),
            )
        )

        capped = session._cap_live_order_decision(
            make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=84.0,
                gross_expected_edge_bps=30.0,
                net_expected_edge_bps=18.0,
                estimated_round_trip_cost_bps=10.0,
                order_intent_notional_usd=120.0,
            ),
            reference_price=50000.0,
        )

        self.assertEqual(capped.final_mode, "futures")
        self.assertAlmostEqual(capped.order_intent_notional_usd, 1282.5, places=6)
        self.assertIn("HIGH_CONVICTION_A_PLUS_SIZE", capped.size_boost_reasons)

    def test_high_conviction_reversal_unlock_requires_clean_long_sequence(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=0.9,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                high_conviction_recent_long_confirmations=2,
                high_conviction_recent_max_age_minutes=6,
                high_conviction_recent_min_trend_strength=0.5,
                high_conviction_recent_min_volume_confirmation=0.4,
                high_conviction_recent_min_liquidity=0.3,
                high_conviction_recent_max_volatility_penalty=0.85,
                high_conviction_recent_max_overheat_penalty=0.65,
                high_conviction_recent_min_edge_to_cost_multiple=1.15,
                high_conviction_recent_opposite_block_enabled=True,
                high_conviction_recent_opposite_max_age_minutes=6,
                high_conviction_recent_reversal_unlock_enabled=True,
                high_conviction_recent_reversal_unlock_confirmations=3,
                strong_score_buffer=18.0,
                strong_trend_strength_min=0.64,
                strong_volume_confirmation_min=0.55,
                strong_liquidity_min=0.3,
                strong_volatility_penalty_max=1.0,
                strong_overheat_penalty_max=0.8,
                strong_edge_to_cost_multiple_min=1.2,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        session.decisions.extend(
            (
                make_decision(timestamp=now - timedelta(minutes=4), symbol="BTCUSDT", side="short"),
                make_decision(timestamp=now - timedelta(minutes=2), symbol="BTCUSDT", predictability_score=82.0),
                replace(
                    make_decision(timestamp=now - timedelta(minutes=1), symbol="BTCUSDT", predictability_score=83.0),
                    trend_strength=0.3,
                ),
            )
        )

        capped = session._cap_live_order_decision(
            make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=84.0,
                gross_expected_edge_bps=30.0,
                net_expected_edge_bps=18.0,
                estimated_round_trip_cost_bps=10.0,
                order_intent_notional_usd=120.0,
            ),
            reference_price=50000.0,
        )

        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("HIGH_CONVICTION_RECENT_LONG_CONFIRMATION_REQUIRED", capped.rejection_reasons)

    def test_high_conviction_blocks_recent_overheated_fake_pump_confirmation(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            mode_thresholds=replace(self.settings.mode_thresholds, futures_score_min=52.0),
            risk=replace(
                self.settings.risk,
                target_futures_leverage=30.0,
                max_futures_leverage=30.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
            cash_reserve=replace(self.settings.cash_reserve, when_futures_enabled=0.05),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
                high_conviction_sizing_enabled=True,
                high_conviction_block_non_strong=True,
                high_conviction_target_margin_fraction=0.9,
                high_conviction_medium_margin_fraction=0.35,
                high_conviction_min_notional_usd=120.0,
                high_conviction_recent_long_confirmations=2,
                high_conviction_recent_max_age_minutes=6,
                high_conviction_recent_min_trend_strength=0.5,
                high_conviction_recent_min_volume_confirmation=0.4,
                high_conviction_recent_min_liquidity=0.3,
                high_conviction_recent_max_volatility_penalty=0.85,
                high_conviction_recent_max_overheat_penalty=0.65,
                high_conviction_recent_min_edge_to_cost_multiple=1.15,
                strong_score_buffer=18.0,
                strong_trend_strength_min=0.64,
                strong_volume_confirmation_min=0.55,
                strong_liquidity_min=0.3,
                strong_volatility_penalty_max=1.0,
                strong_overheat_penalty_max=0.8,
                strong_edge_to_cost_multiple_min=1.2,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        session.decisions.append(
            replace(
                make_decision(timestamp=now - timedelta(minutes=1), symbol="BTCUSDT", predictability_score=82.0),
                overheat_penalty=0.75,
            )
        )

        capped = session._cap_live_order_decision(
            make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=82.0,
                gross_expected_edge_bps=30.0,
                net_expected_edge_bps=18.0,
                estimated_round_trip_cost_bps=10.0,
                order_intent_notional_usd=120.0,
            ),
            reference_price=50000.0,
        )

        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("HIGH_CONVICTION_RECENT_LONG_CONFIRMATION_REQUIRED", capped.rejection_reasons)

    def test_cap_live_order_decision_does_not_scale_up_alt_on_operational_aggressive_pass(self) -> None:
        session = self._build_session()
        session.capital_report = {
            "futures_execution_balance_usd": 10000.0,
            "futures_requirements": [{"symbol": "XRPUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01}],
        }
        session.live_orders = [
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 15.0, "realized_edge_bps": 15.0},
            {"symbol": "ETHUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 16.0, "realized_edge_bps": 16.0},
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 17.0, "realized_edge_bps": 17.0},
            {"symbol": "ETHUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 18.0, "realized_edge_bps": 18.0},
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 19.0, "realized_edge_bps": 19.0},
            {"symbol": "ETHUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 20.0, "realized_edge_bps": 20.0},
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 21.0, "realized_edge_bps": 21.0},
            {"symbol": "ETHUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 22.0, "realized_edge_bps": 22.0},
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.99, "expected_net_edge_bps": 23.0, "realized_edge_bps": 23.0},
            {"symbol": "ETHUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.98, "expected_net_edge_bps": 24.0, "realized_edge_bps": 24.0},
        ]
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        capped = session._cap_live_order_decision(make_decision(timestamp=now, symbol="XRPUSDT", order_intent_notional_usd=1000.0), reference_price=150.0)
        self.assertEqual(capped.final_mode, "futures")
        self.assertAlmostEqual(capped.order_intent_notional_usd, 500.0, places=6)
        self.assertIn("NON_MAJOR_CONSERVATIVE_OVERRIDE", capped.size_boost_reasons)
        self.assertNotIn("OPERATIONAL_AGGRESSIVE_PASS_SCALE", capped.size_boost_reasons)

    def test_cap_live_order_decision_does_not_scale_up_alt_on_operational_strong_pass(self) -> None:
        session = self._build_session()
        session.capital_report = {
            "futures_execution_balance_usd": 10000.0,
            "futures_requirements": [{"symbol": "XRPUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01}],
        }
        session.live_orders = [
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 15.0, "realized_edge_bps": 13.0},
            {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 14.0, "realized_edge_bps": 12.0},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.97, "expected_net_edge_bps": 16.0, "realized_edge_bps": 13.6},
            {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 15.0, "realized_edge_bps": 12.5},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 17.0, "realized_edge_bps": 14.4},
            {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 13.0, "realized_edge_bps": 11.0},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.97, "expected_net_edge_bps": 18.0, "realized_edge_bps": 15.0},
            {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 16.0, "realized_edge_bps": 13.4},
        ]
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        capped = session._cap_live_order_decision(make_decision(timestamp=now, symbol="XRPUSDT", order_intent_notional_usd=1000.0), reference_price=150.0)
        self.assertEqual(capped.final_mode, "futures")
        self.assertAlmostEqual(capped.order_intent_notional_usd, 1000.0, places=6)
        self.assertIn("NON_MAJOR_CONSERVATIVE_OVERRIDE", capped.size_boost_reasons)
        self.assertNotIn("OPERATIONAL_STRONG_PASS_SCALE", capped.size_boost_reasons)

    def test_cap_live_order_decision_scales_up_on_operational_strong_pass(self) -> None:
        session = self._build_session()
        session.capital_report = {
            "futures_execution_balance_usd": 10000.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        session.live_orders = [
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 15.0, "realized_edge_bps": 13.0},
            {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 14.0, "realized_edge_bps": 12.0},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.97, "expected_net_edge_bps": 16.0, "realized_edge_bps": 13.6},
            {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 15.0, "realized_edge_bps": 12.5},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 17.0, "realized_edge_bps": 14.4},
            {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 13.0, "realized_edge_bps": 11.0},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.97, "expected_net_edge_bps": 18.0, "realized_edge_bps": 15.0},
            {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 16.0, "realized_edge_bps": 13.4},
        ]
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        capped = session._cap_live_order_decision(make_decision(timestamp=now, order_intent_notional_usd=1000.0), reference_price=50000.0)
        self.assertEqual(capped.final_mode, "futures")
        self.assertAlmostEqual(capped.order_intent_notional_usd, 1150.0, places=6)
        self.assertIn("OPERATIONAL_STRONG_PASS_SCALE", capped.size_boost_reasons)

    def test_cap_live_order_decision_blocks_new_entries_on_early_operational_stop(self) -> None:
        session = self._build_session()
        session.capital_report = {
            "futures_execution_balance_usd": 5000.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        session.live_orders = [
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.8, "expected_net_edge_bps": 20.0, "realized_edge_bps": 2.0},
            {"symbol": "ETHUSDT", "accepted": False, "fill_status": "reject", "fill_ratio": 0.0, "expected_net_edge_bps": 12.0, "realized_edge_bps": 0.0, "protection_error": "timeout"},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.8, "expected_net_edge_bps": 18.0, "realized_edge_bps": 3.0},
        ]
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        capped = session._cap_live_order_decision(make_decision(timestamp=now, order_intent_notional_usd=1000.0), reference_price=50000.0)
        self.assertEqual(capped.final_mode, "cash")
        self.assertEqual(capped.side, "flat")
        self.assertIn("OPERATIONAL_STOP", capped.rejection_reasons)

    def test_cap_live_order_decision_blocks_new_entries_on_operational_stop(self) -> None:
        session = self._build_session()
        session.capital_report = {
            "futures_execution_balance_usd": 5000.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        session.live_orders = [
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.8, "expected_net_edge_bps": 20.0, "realized_edge_bps": 2.0},
            {"symbol": "ETHUSDT", "accepted": False, "fill_status": "reject", "fill_ratio": 0.0, "expected_net_edge_bps": 12.0, "realized_edge_bps": 0.0, "protection_error": "timeout"},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.8, "expected_net_edge_bps": 18.0, "realized_edge_bps": 3.0},
            {"symbol": "ETHUSDT", "accepted": False, "fill_status": "reject", "fill_ratio": 0.0, "expected_net_edge_bps": 10.0, "realized_edge_bps": 0.0, "protection_error": "timeout"},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.8, "expected_net_edge_bps": 16.0, "realized_edge_bps": 2.0},
        ]
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        capped = session._cap_live_order_decision(make_decision(timestamp=now, order_intent_notional_usd=1000.0), reference_price=50000.0)
        self.assertEqual(capped.final_mode, "cash")
        self.assertEqual(capped.side, "flat")
        self.assertIn("OPERATIONAL_STOP", capped.rejection_reasons)

    def test_cap_live_order_decision_blocks_opposite_btc_eth_major_positions(self) -> None:
        session = self._build_session()
        session.capital_report = {
            "futures_execution_balance_usd": 1000.0,
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        session.paper_positions["ETHUSDT"] = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol="ETHUSDT",
            market="futures",
            side="short",
            entry_time=now,
            entry_price=2500.0,
            current_price=2450.0,
            quantity_opened=0.5,
            quantity_remaining=0.5,
            stop_distance_bps=500.0,
            active_stop_price=2550.0,
            best_price=2450.0,
            worst_price=2500.0,
            entry_predictability_score=82.0,
            entry_liquidity_score=0.8,
            entry_net_expected_edge_bps=18.0,
            entry_estimated_round_trip_cost_bps=10.0,
            entry_planned_leverage=3,
        )
        capped = session._cap_live_order_decision(make_decision(timestamp=now, symbol="BTCUSDT", side="long"), reference_price=50000.0)
        self.assertEqual(capped.final_mode, "cash")
        self.assertEqual(capped.side, "flat")
        self.assertIn("MAJOR_CROSS_SYMBOL_SIDE_CONFLICT", capped.rejection_reasons)
        self.assertIn("MAJOR_SIDE_CONFLICT:ETHUSDT", capped.rejection_reasons)

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
        session = self._build_session(settings=replace(self.settings, ensemble_signal_required=False))
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
            validation_report_path = summary_path.with_name("validation_report.json")
            self.assertEqual(summary["decision_count"], 1)
            self.assertEqual(summary["tested_order_count"], 1)
            self.assertEqual(summary["observe_only_symbols"], ["SIGNUSDT"])
            self.assertTrue(summary_path.exists())
            self.assertTrue(state_path.exists())
            policy_state_path = summary_path.with_name("policy_state.json")
            policy_history_path = summary_path.with_name("policy_history.jsonl")
            comparison_report_path = summary_path.with_name("policy_comparison.json")
            self.assertTrue(policy_state_path.exists())
            self.assertTrue(policy_history_path.exists())
            self.assertTrue(comparison_report_path.exists())
            policy_payload = json.loads(policy_state_path.read_text(encoding="utf-8"))
            self.assertIn("active_policy", policy_payload)
            self.assertIn("policy_validation", policy_payload)
            self.assertIn("policy_evidence_buckets", policy_payload)
            self.assertIn("active_policy", policy_payload["policy_evidence_buckets"])
            self.assertIn("runner_max_drawdown_pct", policy_payload["policy_validation"]["evidence"])
            self.assertIn("candidate_vs_current_score_delta", policy_payload["policy_validation"]["evidence"])
            self.assertIn("policy_evidence_buckets", summary)
            self.assertIn("policy_lineage", summary)
            self.assertIn("live_evidence_rejudge", summary)
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state_payload["live_decision_loop"]["closed_decision_kline_count"], 1)
            self.assertEqual(state_payload["live_decision_loop"]["emitted_decision_count"], 1)
            self.assertIn("policy_state", state_payload)
            self.assertIn("policy_evidence_buckets", state_payload)
            self.assertIn("policy_lineage", state_payload)
            self.assertIn("live_evidence_rejudge", state_payload)
        finally:
            if summary_path.exists():
                summary_path.unlink()
            if state_path.exists():
                state_path.unlink()
            policy_state_path = summary_path.with_name("policy_state.json")
            policy_history_path = summary_path.with_name("policy_history.jsonl")
            if policy_state_path.exists():
                policy_state_path.unlink()
            validation_report_path = summary_path.with_name("validation_report.json")
            comparison_report_path = summary_path.with_name("policy_comparison.json")
            if policy_history_path.exists():
                policy_history_path.unlink()
            if validation_report_path.exists():
                validation_report_path.unlink()
            if comparison_report_path.exists():
                comparison_report_path.unlink()

    def test_session_flush_recomputes_promotion_verdict_from_policy_comparison(self) -> None:
        session = self._build_session()
        session.live_orders = [
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 15.0, "realized_edge_bps": 13.0},
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 16.0, "realized_edge_bps": 13.2},
            {"symbol": "BTCUSDT", "side": "long", "accepted": True, "fill_status": "filled", "fill_ratio": 0.97, "expected_net_edge_bps": 15.0, "realized_edge_bps": 12.0},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "quant_runtime"
            run_dir = base / "output" / "paper-live-shell" / "run-a"
            run_dir.mkdir(parents=True, exist_ok=True)
            summary_path = run_dir / "summary.json"
            state_path = run_dir / "summary.state.json"
            summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "active_policy": {
                            "status": "promote_aggressive",
                            "adjustments": [
                                {
                                    "symbol": "BTCUSDT",
                                    "action": "aggressive_promote",
                                    "size_multiplier": 1.25,
                                    "leverage_multiplier": 1.2,
                                    "entry_threshold_bps": -1.5,
                                    "expected_profit_floor_bps": -2.0,
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            summary = session.flush(summary_path=summary_path, state_path=state_path)
            policy_payload = json.loads(summary_path.with_name("policy_state.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["promotion_verdict"]["status"], "keep")
            self.assertEqual(summary["promotion_verdict"]["comparison_verdict"], "candidate_worse")
            self.assertEqual(policy_payload["status"], "rolled_back")
            self.assertEqual(policy_payload["active_policy"]["status"], "baseline")

    def test_session_filters_persisted_policy_and_execution_quality_to_runtime_universe(self) -> None:
        settings = replace(
            self.settings,
            universe=("BTCUSDT",),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
                priority_symbols=("BTCUSDT",),
            ),
        )
        session = self._build_session(settings=settings)
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "output" / "paper-live-shell" / "run-a"
            run_dir.mkdir(parents=True, exist_ok=True)
            summary_path = run_dir / "summary.json"
            state_path = run_dir / "summary.state.json"
            session.summary_path = summary_path

            policy_state_path = summary_path.with_name("policy_state.json")
            policy_state_path.write_text(
                json.dumps(
                    {
                        "active_policy": {
                            "status": "promote",
                            "adjustments": [
                                {"symbol": "BTCUSDT", "action": "promote"},
                                {"symbol": "DOGEUSDT", "action": "demote"},
                            ],
                        },
                        "symbol_lifecycle": [
                            {"symbol": "BTCUSDT", "recommended_action": "keep"},
                            {"symbol": "DOGEUSDT", "recommended_action": "hold"},
                        ],
                        "policy_evidence_buckets": {
                            "active_policy": {
                                "available": True,
                                "alignment": {"aligned": True, "status": "aligned"},
                                "evidence": {
                                    "checkpoint_auto_judge": {
                                        "symbol_actions": [
                                            {"symbol": "BTCUSDT", "action": "keep"},
                                            {"symbol": "DOGEUSDT", "action": "hold"},
                                        ]
                                    }
                                },
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            session._execution_quality_state.record(
                symbol="BTCUSDT",
                outcome="filled",
                fill_ratio=1.0,
                slippage_bps=0.0,
                realized_edge_bps=10.0,
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                market="futures",
                exchange_id="binance",
                policy_bucket="active_policy",
            )
            session._execution_quality_state.record(
                symbol="DOGEUSDT",
                outcome="filled",
                fill_ratio=1.0,
                slippage_bps=0.0,
                realized_edge_bps=8.0,
                timestamp=datetime(2026, 3, 8, 12, 6, tzinfo=timezone.utc),
                market="futures",
                exchange_id="binance",
                policy_bucket="active_policy",
            )

            persisted = session._read_persisted_policy_state()
            self.assertEqual(
                [row["symbol"] for row in persisted["active_policy"]["adjustments"]],
                ["BTCUSDT"],
            )
            self.assertEqual(
                [row["symbol"] for row in persisted["symbol_lifecycle"]],
                ["BTCUSDT"],
            )

            summary = session.flush(summary_path=summary_path, state_path=state_path)
            self.assertIn("BTCUSDT", summary["execution_quality"]["symbols"])
            self.assertNotIn("DOGEUSDT", summary["execution_quality"]["symbols"])
            self.assertNotIn(
                "DOGEUSDT|market=futures|exchange=binance|policy_bucket=active_policy",
                summary["execution_quality"]["contexts"],
            )

    def test_session_flush_persists_separated_execution_replay_comparison(self) -> None:
        session = self._build_session()
        session.live_orders = [
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.97, "expected_net_edge_bps": 16.0, "realized_edge_bps": 14.5},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 15.0, "realized_edge_bps": 13.2},
            {"symbol": "ETHUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 13.0, "realized_edge_bps": 11.0},
        ]
        session.closed_trades = [
            {"symbol": "BTCUSDT", "market": "futures", "realized_pnl_usd_estimate": 4.0, "realized_return_bps_estimate": 10.0},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "quant_runtime"
            run_dir = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            summary_path = run_dir / "summary.json"
            state_path = run_dir / "summary.state.json"
            (logs_dir / "closed_trades.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 4.0, "realized_return_bps_estimate": 10.0}) + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 70.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"}),
                        json.dumps({"symbol": "ETHUSDT", "final_mode": "futures", "predictability_score": 69.0, "net_expected_edge_bps": 10.5, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:05:00+00:00"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "version": 2,
                        "rollout_progression": {"execution_phase": "partial"},
                        "active_policy": {
                            "status": "promote",
                            "adjustments": [
                                {
                                    "symbol": "BTCUSDT",
                                    "action": "promote",
                                    "size_multiplier": 1.1,
                                    "leverage_multiplier": 1.05,
                                    "entry_threshold_bps": -0.5,
                                    "expected_profit_floor_bps": -1.0,
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            summary = session.flush(summary_path=summary_path, state_path=state_path)
            comparison_payload = json.loads(summary_path.with_name("policy_comparison.json").read_text(encoding="utf-8"))
            policy_validation_evidence = summary["policy_validation"]["evidence"]
            self.assertIn("comparison_execution_replay_verdict", comparison_payload)
            self.assertIn("candidate_vs_current_execution_replay_score_delta", comparison_payload)
            self.assertEqual(
                comparison_payload["counterfactual_replay_path"]["current_policy"]["runtime_summary_anchor"]["source"],
                "current_runtime_summary",
            )
            self.assertEqual(
                comparison_payload["counterfactual_replay_path"]["current_policy"]["source"],
                "observed_runtime_artifacts",
            )
            self.assertIn("execution_path_comparison", policy_validation_evidence)
            self.assertIn("replay_evidence_comparison", policy_validation_evidence)
            self.assertIn("execution_replay_metric_delta", policy_validation_evidence)
            self.assertEqual(
                policy_validation_evidence["comparison_execution_replay_verdict"],
                comparison_payload["comparison_execution_replay_verdict"],
            )

    def test_session_flush_persists_pending_micro_live_gate_staging(self) -> None:
        session = self._build_session()
        session.live_orders = [
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.95, "expected_net_edge_bps": 16.0, "realized_edge_bps": 14.0},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 16.0, "realized_edge_bps": 14.0},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.97, "expected_net_edge_bps": 15.0, "realized_edge_bps": 13.5},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "quant_runtime"
            run_dir = base / "output" / "paper-live-shell" / "run-a"
            run_dir.mkdir(parents=True, exist_ok=True)
            summary_path = run_dir / "summary.json"
            state_path = run_dir / "summary.state.json"
            summary = session.flush(summary_path=summary_path, state_path=state_path)
            policy_path = summary_path.with_name("policy_state.json")
            history_path = summary_path.with_name("policy_history.jsonl")
            payload = json.loads(policy_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "staged_rollout")
            self.assertEqual(payload["rollout_status"], "micro_live_pending")
            self.assertEqual(payload["rollout_progression"]["status"], "collecting_micro_live_outcomes")
            self.assertEqual(payload["rollout_progression"]["execution_phase"], "partial")
            history_entries = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(history_entries[-1]["status"], "staged_rollout")
            self.assertEqual(summary["promotion_verdict"]["status"], "keep")
            self.assertIn("PROMOTION_BLOCKED_BY_MICRO_LIVE_GATE", summary["promotion_verdict"]["reasons"])

    def test_session_flush_promotes_resumed_staged_candidate_after_micro_live_pass(self) -> None:
        session = self._build_session()
        session.live_orders = [
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.96, "expected_net_edge_bps": 15.0, "realized_edge_bps": 13.5},
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.97, "expected_net_edge_bps": 15.5, "realized_edge_bps": 14.0},
        ]
        session.closed_trades = [
            {"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 4.0, "realized_return_bps_estimate": 10.0},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "quant_runtime"
            run_dir = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_dir / "logs"
            run_dir.mkdir(parents=True, exist_ok=True)
            logs_dir.mkdir(parents=True, exist_ok=True)
            summary_path = run_dir / "summary.json"
            state_path = run_dir / "summary.state.json"
            (logs_dir / "closed_trades.jsonl").write_text(
                json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 4.0, "realized_return_bps_estimate": 10.0}) + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 70.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"}),
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 71.0, "net_expected_edge_bps": 12.5, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:05:00+00:00"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "status": "staged_rollout",
                        "rollout_status": "micro_live_pending",
                        "active_policy": {"status": "baseline", "adjustments": []},
                        "candidate_policy": {
                            "status": "candidate_ready",
                            "adjustments": [
                                {
                                    "symbol": "BTCUSDT",
                                    "action": "promote",
                                    "size_multiplier": 1.1,
                                    "leverage_multiplier": 1.1,
                                    "entry_threshold_bps": -0.5,
                                    "expected_profit_floor_bps": -1.0,
                                    "signal_sources": ["runtime_symbol_summary"],
                                }
                            ],
                            "signal_sources": ["runtime_symbol_summary"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            summary = session.flush(summary_path=summary_path, state_path=state_path)
            payload = json.loads(summary_path.with_name("policy_state.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["candidate_policy"]["decomposition_summary"]["resumed_from_staged_rollout"])
            self.assertEqual(summary["promotion_verdict"]["status"], "promote")
            self.assertEqual(payload["status"], "promoted")
            self.assertEqual(payload["active_policy"]["status"], "promote")
            self.assertEqual(payload["rollout_status"], "ready")
            self.assertEqual(payload["rollout_progression"]["status"], "post_promotion_monitoring")
            self.assertEqual(payload["rollout_progression"]["execution_phase"], "partial")

    def test_session_flush_rolls_back_after_post_promotion_retention_degrades(self) -> None:
        session = self._build_session()
        session.live_orders = [
            {"symbol": "BTCUSDT", "accepted": True, "fill_status": "filled", "fill_ratio": 0.9, "expected_net_edge_bps": 12.0, "realized_edge_bps": -1.0},
            {"symbol": "BTCUSDT", "accepted": False, "fill_status": "reject", "fill_ratio": 0.0, "expected_net_edge_bps": 10.0, "realized_edge_bps": 0.0},
            {"symbol": "BTCUSDT", "accepted": False, "fill_status": "reject", "fill_ratio": 0.0, "expected_net_edge_bps": 10.0, "realized_edge_bps": 0.0, "protection_error": "timeout"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "quant_runtime"
            run_dir = base / "output" / "paper-live-shell" / "run-a"
            run_dir.mkdir(parents=True, exist_ok=True)
            summary_path = run_dir / "summary.json"
            state_path = run_dir / "summary.state.json"
            summary_path.with_name("policy_state.json").write_text(json.dumps({"version": 2, "active_policy": {"status": "promote", "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1}]}, "rollout_status": "ready"}), encoding="utf-8")
            session.flush(summary_path=summary_path, state_path=state_path)
            payload = json.loads(summary_path.with_name("policy_state.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "rolled_back")
            self.assertEqual(payload["rollout_reason"], "OPERATIONAL_STOP_ACTIVE")
            self.assertEqual(payload["retention_monitor"]["status"], "inactive")
            self.assertEqual(payload["rollout_progression"]["status"], "reverted")
            self.assertEqual(payload["rollout_progression"]["execution_phase"], "baseline")

    def test_persisted_policy_state_rolls_back_on_cumulative_retention_collapse(self) -> None:
        payload = build_persisted_policy_state(
            {
                "version": 2,
                "active_policy": {
                    "status": "promote",
                    "adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1, "leverage_multiplier": 1.1}],
                },
                "rollout_status": "ready",
            },
            {"adjustments": [{"symbol": "BTCUSDT", "action": "promote", "size_multiplier": 1.1, "leverage_multiplier": 1.1}]},
            {"status": "promote", "requested_status": "promote", "effective_status": "promote"},
            {"status": "pass"},
            {
                "status": "pass",
                "evidence": {
                    "runner_total_realized_pnl_usd": 5.0,
                    "runner_drawdown_to_pnl_ratio": 0.2,
                    "runner_reject_rate": 0.02,
                    "runner_avg_slippage_bps": 3.0,
                    "runner_avg_realized_edge_bps": 6.0,
                    "runner_avg_edge_retention_ratio": 0.82,
                    "runner_walk_forward_window_count": 4,
                    "runner_positive_walk_forward_ratio": 0.75,
                    "micro_live_gate": {"available": True, "status": "pass"},
                    "validation_runs": [
                        {"run_id": "run-a", "live_order_count": 10, "accepted_live_order_count": 10, "rejected_live_order_count": 0, "closed_trade_count": 2, "avg_edge_retention_ratio": 0.1, "avg_slippage_bps": 2.0, "realized_pnl_usd": -6.0},
                        {"run_id": "run-b", "live_order_count": 1, "accepted_live_order_count": 1, "rejected_live_order_count": 0, "closed_trade_count": 1, "avg_edge_retention_ratio": 0.9, "avg_slippage_bps": 2.0, "realized_pnl_usd": 4.0},
                        {"run_id": "run-c", "live_order_count": 1, "accepted_live_order_count": 1, "rejected_live_order_count": 0, "closed_trade_count": 1, "avg_edge_retention_ratio": 0.9, "avg_slippage_bps": 2.0, "realized_pnl_usd": 4.0},
                        {"run_id": "run-d", "live_order_count": 1, "accepted_live_order_count": 1, "rejected_live_order_count": 0, "closed_trade_count": 1, "avg_edge_retention_ratio": 0.9, "avg_slippage_bps": 2.0, "realized_pnl_usd": 3.0},
                    ],
                    "walk_forward_windows": [
                        {"window_index": 1, "avg_net_edge_bps": 2.0, "avg_score": 0.2},
                        {"window_index": 2, "avg_net_edge_bps": 3.0, "avg_score": 0.3},
                        {"window_index": 3, "avg_net_edge_bps": 4.0, "avg_score": 0.3},
                        {"window_index": 4, "avg_net_edge_bps": 5.0, "avg_score": 0.4},
                    ],
                },
            },
        )
        self.assertEqual(payload["retention_monitor"]["status"], "rollback")
        self.assertIn("RETENTION_MONITOR_CUMULATIVE_EDGE_COLLAPSE", payload["retention_monitor"]["reasons"])
        self.assertEqual(payload["rollout_reason"], "POST_PROMOTION_RETENTION_DEGRADED")
    def test_session_flush_recomputes_candidate_policy_from_validation_report_decomposition(self) -> None:
        session = self._build_session()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "quant_runtime"
            run_dir = base / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            summary_path = run_dir / "summary.json"
            state_path = run_dir / "summary.state.json"
            (logs_dir / "closed_trades.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 5.0, "realized_return_bps_estimate": 12.0}),
                        json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 4.0, "realized_return_bps_estimate": 10.0}),
                        json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": 3.0, "realized_return_bps_estimate": 8.0}),
                        json.dumps({"symbol": "SOLUSDT", "realized_pnl_usd_estimate": -3.0, "realized_return_bps_estimate": -8.0}),
                        json.dumps({"symbol": "SOLUSDT", "realized_pnl_usd_estimate": -2.0, "realized_return_bps_estimate": -6.0}),
                        json.dumps({"symbol": "SOLUSDT", "realized_pnl_usd_estimate": -1.0, "realized_return_bps_estimate": -4.0}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (logs_dir / "decisions.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 70.0, "net_expected_edge_bps": 12.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:00:00+00:00"}),
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 71.0, "net_expected_edge_bps": 12.5, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:05:00+00:00"}),
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 72.0, "net_expected_edge_bps": 13.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:10:00+00:00"}),
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 73.0, "net_expected_edge_bps": 13.5, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:15:00+00:00"}),
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 74.0, "net_expected_edge_bps": 14.0, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:20:00+00:00"}),
                        json.dumps({"symbol": "BTCUSDT", "final_mode": "futures", "predictability_score": 75.0, "net_expected_edge_bps": 14.5, "estimated_round_trip_cost_bps": 8.0, "timestamp": "2026-03-14T00:25:00+00:00"}),
                        json.dumps({"symbol": "SOLUSDT", "final_mode": "cash", "predictability_score": 40.0, "net_expected_edge_bps": -1.0, "estimated_round_trip_cost_bps": 10.0, "timestamp": "2026-03-14T00:30:00+00:00", "rejection_reasons": ["LIQUIDITY_TOO_WEAK", "EDGE_TOO_THIN"]}),
                        json.dumps({"symbol": "SOLUSDT", "final_mode": "cash", "predictability_score": 38.0, "net_expected_edge_bps": -1.5, "estimated_round_trip_cost_bps": 10.0, "timestamp": "2026-03-14T00:35:00+00:00", "rejection_reasons": ["LIQUIDITY_TOO_WEAK", "EDGE_TOO_THIN"]}),
                        json.dumps({"symbol": "SOLUSDT", "final_mode": "cash", "predictability_score": 39.0, "net_expected_edge_bps": -1.2, "estimated_round_trip_cost_bps": 10.0, "timestamp": "2026-03-14T00:40:00+00:00", "rejection_reasons": ["LIQUIDITY_TOO_WEAK", "EDGE_TOO_THIN"]}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            summary = session.flush(summary_path=summary_path, state_path=state_path)
            adjustments = {item["symbol"]: item for item in summary["candidate_policy"]["adjustments"]}
            self.assertEqual(adjustments["SOLUSDT"]["action"], "demote")
            self.assertIn("runtime_pruning_recommendation", adjustments["SOLUSDT"]["signal_sources"])
            self.assertNotIn("BTCUSDT", adjustments)
            lifecycle_overlay = summary["candidate_policy"]["decomposition_summary"]["symbol_lifecycle_overlay"]
            self.assertEqual(lifecycle_overlay["blocked_symbols"], ["BTCUSDT"])
            self.assertEqual(lifecycle_overlay["re_review_symbols"], ["BTCUSDT"])

    def test_session_flush_blocks_symbol_promotion_when_rolling_evidence_is_mixed(self) -> None:
        session = self._build_session()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "quant_runtime"
            run_root = base / "output" / "paper-live-shell"
            for index, (run_name, pnl) in enumerate((("run-a", 8.0), ("run-b", -7.0), ("run-c", 1.0)), start=1):
                run_dir = run_root / run_name
                logs_dir = run_dir / "logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "summary.json").write_text(
                    json.dumps({"live_order_count": 1, "tested_order_count": 0}),
                    encoding="utf-8",
                )
                (logs_dir / "closed_trades.jsonl").write_text(
                    json.dumps({"symbol": "BTCUSDT", "realized_pnl_usd_estimate": pnl, "realized_return_bps_estimate": pnl * 2.0}) + "\n",
                    encoding="utf-8",
                )
                (logs_dir / "decisions.jsonl").write_text(
                    json.dumps(
                        {
                            "symbol": "BTCUSDT",
                            "final_mode": "futures",
                            "predictability_score": 70.0,
                            "net_expected_edge_bps": 12.0,
                            "estimated_round_trip_cost_bps": 8.0,
                            "timestamp": f"2026-03-14T00:0{index}:00+00:00",
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            summary_path = run_root / "run-c" / "summary.json"
            state_path = run_root / "run-c" / "summary.state.json"
            summary = session.flush(summary_path=summary_path, state_path=state_path)
            adjustments = {item["symbol"]: item for item in summary["candidate_policy"]["adjustments"]}
            self.assertNotIn("BTCUSDT", adjustments)
            self.assertEqual(summary["candidate_policy"]["status"], "insufficient_data")

    def test_session_flush_rewrites_validation_report_even_when_stale_file_exists(self) -> None:
        session = self._build_session()
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "quant_runtime"
            run_dir = base / "output" / "paper-live-shell" / "run-a"
            run_dir.mkdir(parents=True, exist_ok=True)
            summary_path = run_dir / "summary.json"
            state_path = run_dir / "summary.state.json"
            validation_report_path = run_dir / "validation_report.json"
            validation_report_path.write_text(
                json.dumps({"runner_total_return_pct": -999.0, "evidence": {"runner_total_return_pct": -999.0}}),
                encoding="utf-8",
            )
            session.flush(summary_path=summary_path, state_path=state_path)
            validation_payload = json.loads(validation_report_path.read_text(encoding="utf-8"))
            self.assertNotEqual(validation_payload["runner_total_return_pct"], -999.0)
            self.assertEqual(validation_payload["validation_path_mode"], "paper_live_walk_forward_artifacts")

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

    def test_execute_recorded_bootstrap_decision_runs_submission_path(self) -> None:
        session = self._build_session(settings=replace(self.settings, ensemble_signal_required=False))
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        bootstrap_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)

        recorded = session.run_bootstrap_cycle(
            state=state,
            primitive_inputs=make_primitive(),
            history=make_history(),
            decision_time=bootstrap_time,
        )

        session._execute_recorded_decision(
            managed_decision=recorded,
            state=state,
            timestamp=bootstrap_time,
        )

        self.assertEqual(len(session.decisions), 1)
        self.assertEqual(len(session.tested_orders), 1)
        self.assertEqual(session.tested_orders[0]["symbol"], "BTCUSDT")

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

    def test_session_runs_subminute_scheduled_decision_boundary(self) -> None:
        settings = replace(
            self.settings,
            decision_engine=replace(
                self.settings.decision_engine,
                decision_interval_minutes=1,
                decision_interval_seconds=15,
            ),
        )
        session = self._build_session(settings=settings)
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
                    "E": int(datetime(2026, 3, 8, 12, 5, 15, tzinfo=timezone.utc).timestamp() * 1000),
                    "m": False,
                },
            },
            now=datetime(2026, 3, 8, 12, 5, 15, tzinfo=timezone.utc),
        )

        self.assertIsNone(decision)
        self.assertEqual(len(session.decisions), 2)
        self.assertEqual(session.decisions[-1].symbol, "BTCUSDT")
        self.assertEqual(session.decisions[-1].timestamp.isoformat(), "2026-03-08T12:05:15+00:00")

    def test_record_decision_skips_older_same_symbol_decision(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        newer = make_decision(timestamp=datetime(2026, 3, 8, 12, 5, 30, tzinfo=timezone.utc))
        duplicate = make_decision(timestamp=datetime(2026, 3, 8, 12, 5, 30, tzinfo=timezone.utc))
        older = make_decision(timestamp=datetime(2026, 3, 8, 12, 5, 15, tzinfo=timezone.utc))

        session._record_decision(decision=newer, state=state, timestamp=newer.timestamp)
        session._record_decision(decision=duplicate, state=state, timestamp=duplicate.timestamp)
        session._record_decision(decision=older, state=state, timestamp=older.timestamp)

        self.assertEqual(len(session.decisions), 1)
        self.assertEqual(session.decisions[0].timestamp.isoformat(), "2026-03-08T12:05:30+00:00")
        self.assertEqual(
            session.last_recorded_decision_time_by_symbol["BTCUSDT"].isoformat(),
            "2026-03-08T12:05:30+00:00",
        )

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
        self.assertEqual(session.closed_trades[0]["exit_reason"], "PROACTIVE_PARTIAL_TAKE_PROFIT")
        self.assertEqual(len(session.tested_orders), 1)
        self.assertEqual(session.remaining_portfolio_capacity_usd, starting_capacity - 730.0)

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
            self.assertEqual(summary["closed_trades"][0]["exit_reason"], "PROACTIVE_PARTIAL_TAKE_PROFIT")
            self.assertEqual(summary["closed_trades"][-1]["exit_reason"], "BREAKEVEN_STOP")
            self.assertEqual(summary["open_futures_positions"], [])
            self.assertEqual(summary["realized_pnl_usd_estimate"], 20.0)
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
        self.assertTrue(any("MANUAL_CLOSE_SYNCED" in alert["text"] for alert in session.telegram_alerts))

    @patch("quant_binance.session.send_telegram_message")
    def test_sync_account_keeps_paper_verification_position_missing_on_exchange(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
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
        starting_trade_count = len(session.closed_trades)

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            for _ in range(6):
                session.sync_account()
            with tempfile.TemporaryDirectory() as tmp:
                summary = session.flush(
                    summary_path=Path(tmp) / "summary.json",
                    state_path=Path(tmp) / "summary.state.json",
                )

        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_on_exchange_counts, {})
        self.assertEqual(len(session.closed_trades), starting_trade_count)
        self.assertNotIn("BTCUSDT", session.manual_symbol_cooldowns)
        self.assertEqual(mock_send.call_count, 0)
        self.assertTrue(summary["paper_verification_mode"])
        self.assertFalse(summary["futures_position_mismatch"])
        self.assertEqual(
            summary["futures_position_mismatch_details"],
            {"missing_in_paper": [], "missing_on_exchange": []},
        )

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
    def test_sync_account_fast_manual_close_cleanup_allows_loss_realization_balance_drop(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self._balances = [25.0, 21.5]
                self._balance_index = 0
                self._positions = [
                    [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "long",
                            "total": "10.0",
                            "available": "10.0",
                            "openPriceAvg": "100.0",
                            "markPrice": "99.6",
                            "marginSize": "20.0",
                            "unrealizedPL": "-3.5",
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
        self.assertIn("BTCUSDT", session.paper_positions)

        session.sync_account()

        self.assertNotIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.futures_missing_on_exchange_counts, {})
        self.assertEqual(session.closed_trades[-1]["exit_reason"], "MANUAL_CLOSE_SYNCED")

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

    def test_paper_verify_cap_live_order_rechecks_fee_floor_after_notional_cap(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="fee-floor-test",
            risk=replace(
                self.settings.risk,
                min_expected_profit_usd_per_trade=2.0,
                max_futures_leverage=30.0,
                target_futures_leverage=30.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 35.0,
            "futures_available_balance_usd": 35.0,
            "futures_requirements": [
                {"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
            ],
        }
        decision = replace(
            make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="ETHUSDT",
                predictability_score=82.0,
                liquidity_score=0.9,
                gross_expected_edge_bps=28.5,
                estimated_round_trip_cost_bps=11.5,
                net_expected_edge_bps=17.0,
                order_intent_notional_usd=1500.0,
            ),
            trend_strength=0.9,
            volume_confirmation=0.85,
        )

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            capped = session._cap_live_order_decision(decision, reference_price=2500.0)

        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("EXPECTED_PROFIT_TOO_SMALL_AFTER_CAP", capped.rejection_reasons)

    def test_small_live_equity_requires_wider_fee_profit_buffer(self) -> None:
        class AcceptedLiveExecutor:
            def _exchange_id(self) -> str:
                return "bitget"

            def execute_decision(self, *, decision, reference_price):  # type: ignore[no-untyped-def]
                raise AssertionError("entry should be blocked before live execution")

            def pop_last_preflight_rejection(self):  # type: ignore[no-untyped-def]
                return None

        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                max_futures_leverage=30.0,
                target_futures_leverage=30.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.live_order_executor = AcceptedLiveExecutor()  # type: ignore[assignment]
        session.equity_usd = 5.4
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 5.4,
            "futures_available_balance_usd": 5.4,
            "futures_requirements": [
                {"symbol": "PEPEUSDT", "min_notional_usd": 5.0, "min_quantity": 1000.0},
            ],
        }
        decision = replace(
            make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="PEPEUSDT",
                predictability_score=71.2,
                liquidity_score=0.56,
                gross_expected_edge_bps=40.32,
                net_expected_edge_bps=31.53,
                estimated_round_trip_cost_bps=8.79,
                order_intent_notional_usd=162.1,
            ),
            volume_confirmation=0.62,
        )

        capped = session._cap_live_order_decision(decision, reference_price=0.00000379)

        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("EXPECTED_PROFIT_TOO_SMALL", capped.rejection_reasons)

    def test_cap_live_order_decision_uses_execution_quality_expected_profit_floor_for_degraded_alt(self) -> None:
        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                min_meaningful_futures_notional_usd=0.0,
                min_expected_profit_usd_per_trade=0.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 100.0,
            "futures_available_balance_usd": 100.0,
            "futures_requirements": [{"symbol": "SOLUSDT", "min_notional_usd": 5.0, "min_quantity": 0.1}],
        }
        state = ExecutionQualityState()
        base = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        for minute in range(4):
            state.record(
                symbol="SOLUSDT",
                outcome="filled",
                fill_ratio=1.0,
                slippage_bps=11.0,
                realized_edge_bps=1.5,
                expected_edge_bps=12.0,
                protection_degraded=True,
                timestamp=base + timedelta(minutes=minute),
                market="futures",
                exchange_id="binance",
            )
        degraded = state.apply_overlay(
            make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="SOLUSDT",
                order_intent_notional_usd=100.0,
                net_expected_edge_bps=12.0,
                estimated_round_trip_cost_bps=8.0,
            ),
            exchange_id="binance",
            now=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
        )

        capped = session._cap_live_order_decision(degraded, reference_price=100.0)

        self.assertEqual(capped.final_mode, "cash")
        self.assertIn("EXPECTED_PROFIT_TOO_SMALL", capped.rejection_reasons)

    def test_cap_live_order_decision_relaxes_expected_profit_floor_for_live_ultra_aggressive_btc_eth(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            risk=replace(
                self.settings.risk,
                min_meaningful_futures_notional_usd=0.0,
                min_expected_profit_usd_per_trade=6.0,
                max_futures_leverage=8.0,
                target_futures_leverage=8.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 130.0,
            "futures_available_balance_usd": 130.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                {"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01},
                {"symbol": "SOLUSDT", "min_notional_usd": 5.0, "min_quantity": 0.1},
            ],
        }
        btc = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            order_intent_notional_usd=72.5,
            net_expected_edge_bps=34.0,
        )
        eth = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="ETHUSDT",
            order_intent_notional_usd=72.5,
            net_expected_edge_bps=34.0,
        )
        sol = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="SOLUSDT",
            order_intent_notional_usd=72.5,
            net_expected_edge_bps=34.0,
        )

        capped_btc = session._cap_live_order_decision(btc, reference_price=50000.0)
        capped_eth = session._cap_live_order_decision(eth, reference_price=2000.0)
        capped_sol = session._cap_live_order_decision(sol, reference_price=100.0)

        self.assertEqual(capped_btc.final_mode, "futures")
        self.assertEqual(capped_eth.final_mode, "futures")
        self.assertEqual(capped_sol.final_mode, "futures")
        self.assertNotIn("EXPECTED_PROFIT_TOO_SMALL", capped_btc.rejection_reasons)
        self.assertNotIn("EXPECTED_PROFIT_TOO_SMALL", capped_eth.rejection_reasons)
        self.assertNotIn("EXPECTED_PROFIT_TOO_SMALL", capped_sol.rejection_reasons)

    def test_execution_quality_degraded_alt_does_not_remove_healthy_btc_eth_major_relief(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            risk=replace(
                self.settings.risk,
                min_meaningful_futures_notional_usd=0.0,
                min_expected_profit_usd_per_trade=6.0,
                max_futures_leverage=8.0,
                target_futures_leverage=8.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 130.0,
            "futures_available_balance_usd": 130.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                {"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01},
                {"symbol": "SOLUSDT", "min_notional_usd": 5.0, "min_quantity": 0.1},
            ],
        }
        state = ExecutionQualityState()
        base = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        for minute in range(4):
            state.record(
                symbol="BTCUSDT",
                outcome="filled",
                fill_ratio=1.0,
                slippage_bps=1.0,
                realized_edge_bps=32.0,
                expected_edge_bps=34.0,
                timestamp=base + timedelta(minutes=minute),
                market="futures",
                exchange_id="binance",
            )
            state.record(
                symbol="ETHUSDT",
                outcome="filled",
                fill_ratio=1.0,
                slippage_bps=1.0,
                realized_edge_bps=31.0,
                expected_edge_bps=34.0,
                timestamp=base + timedelta(minutes=minute),
                market="futures",
                exchange_id="binance",
            )
            state.record(
                symbol="SOLUSDT",
                outcome="filled",
                fill_ratio=1.0,
                slippage_bps=11.0,
                realized_edge_bps=1.5,
                expected_edge_bps=12.0,
                protection_degraded=True,
                timestamp=base + timedelta(minutes=minute),
                market="futures",
                exchange_id="binance",
            )

        btc = state.apply_overlay(
            make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                order_intent_notional_usd=72.5,
                net_expected_edge_bps=34.0,
            ),
            exchange_id="binance",
            now=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
        )
        eth = state.apply_overlay(
            make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="ETHUSDT",
                order_intent_notional_usd=72.5,
                net_expected_edge_bps=34.0,
            ),
            exchange_id="binance",
            now=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
        )
        sol = state.apply_overlay(
            make_decision(
                timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                symbol="SOLUSDT",
                order_intent_notional_usd=100.0,
                net_expected_edge_bps=12.0,
                estimated_round_trip_cost_bps=8.0,
            ),
            exchange_id="binance",
            now=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
        )

        capped_btc = session._cap_live_order_decision(btc, reference_price=50000.0)
        capped_eth = session._cap_live_order_decision(eth, reference_price=2000.0)
        capped_sol = session._cap_live_order_decision(sol, reference_price=100.0)

        self.assertEqual(capped_btc.final_mode, "futures")
        self.assertEqual(capped_eth.final_mode, "futures")
        self.assertEqual(capped_sol.final_mode, "futures")
        self.assertNotIn("EXPECTED_PROFIT_TOO_SMALL", capped_btc.rejection_reasons)
        self.assertNotIn("EXPECTED_PROFIT_TOO_SMALL", capped_eth.rejection_reasons)
        self.assertGreater(sol.execution_quality_expected_profit_floor_bps, 0.0)

    def test_cap_live_order_decision_relaxes_major_entry_floor_for_live_ultra_aggressive_btc_eth(self) -> None:
        settings = replace(
            self.settings,
            strategy_profile="live-ultra-aggressive",
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
                major_min_meaningful_notional_usd=120.0,
                major_medium_min_entry_notional_usd=140.0,
                major_strong_min_entry_notional_usd=180.0,
                pyramid_min_predictability_score=58.0,
                strong_score_buffer=0.5,
                strong_trend_strength_min=0.6,
                strong_volume_confirmation_min=0.5,
                strong_liquidity_min=0.42,
                strong_volatility_penalty_max=0.55,
                strong_overheat_penalty_max=0.45,
                strong_edge_to_cost_multiple_min=1.0,
            ),
            risk=replace(
                self.settings.risk,
                min_meaningful_futures_notional_usd=40.0,
                min_expected_profit_usd_per_trade=0.0,
                max_futures_leverage=8.0,
                target_futures_leverage=8.0,
            ),
            mode_thresholds=replace(
                self.settings.mode_thresholds,
                futures_score_min=42.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 8.2,
            "futures_available_balance_usd": 8.2,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                {"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.01},
                {"symbol": "SOLUSDT", "min_notional_usd": 5.0, "min_quantity": 0.1},
            ],
        }
        btc = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            predictability_score=83.0,
            order_intent_notional_usd=4500.0,
            net_expected_edge_bps=42.0,
            estimated_round_trip_cost_bps=8.0,
        )
        eth = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="ETHUSDT",
            predictability_score=79.0,
            order_intent_notional_usd=3177.0,
            net_expected_edge_bps=34.0,
            estimated_round_trip_cost_bps=8.0,
        )
        sol = make_decision(
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="SOLUSDT",
            predictability_score=80.0,
            order_intent_notional_usd=2285.0,
            net_expected_edge_bps=34.0,
            estimated_round_trip_cost_bps=8.0,
        )

        capped_btc = session._cap_live_order_decision(btc, reference_price=50000.0)
        capped_eth = session._cap_live_order_decision(eth, reference_price=2000.0)
        self.assertEqual(capped_btc.final_mode, "futures")
        self.assertEqual(capped_eth.final_mode, "futures")
        self.assertGreater(capped_btc.order_intent_notional_usd, 0.0)
        self.assertGreater(capped_eth.order_intent_notional_usd, 0.0)

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

    def test_pyramid_fill_tracks_micropriced_futures_position(self) -> None:
        settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                pyramid_size_multiplier=0.4,
            ),
        )
        session = self._build_session(settings=settings)
        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        position = PaperPosition(
            symbol="PEPEUSDT",
            market="futures",
            side="long",
            entry_time=entry_time,
            entry_price=0.00000376,
            current_price=0.00000376,
            quantity_opened=33281000.0,
            quantity_remaining=33281000.0,
            stop_distance_bps=250.0,
            active_stop_price=0.00000366,
            best_price=0.00000376,
            worst_price=0.00000376,
            entry_predictability_score=76.0,
            entry_liquidity_score=0.55,
            entry_net_expected_edge_bps=32.0,
            entry_estimated_round_trip_cost_bps=9.5,
            entry_planned_leverage=30,
        )
        decision = make_decision(
            timestamp=entry_time + timedelta(minutes=5),
            symbol="PEPEUSDT",
            predictability_score=64.0,
            net_expected_edge_bps=15.0,
            order_intent_notional_usd=153.34,
        )
        original_quantity = position.quantity_remaining

        session._apply_pyramid_fill_to_position(
            position=position,
            decision=decision,
            price=0.00000377,
        )

        self.assertGreater(position.quantity_remaining, original_quantity)
        self.assertEqual(session.futures_pyramid_add_counts["PEPEUSDT"], 1)

    def test_paper_position_payload_preserves_micro_price_precision(self) -> None:
        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        position = PaperPosition(
            symbol="PEPEUSDT",
            market="futures",
            side="long",
            entry_time=entry_time,
            entry_price=0.0000038851,
            current_price=0.0000038827,
            quantity_opened=51478726.41630846,
            quantity_remaining=51478726.41630846,
            stop_distance_bps=278.352828,
            active_stop_price=0.0000037769,
            best_price=0.000003887,
            worst_price=0.0000038802,
            entry_predictability_score=75.438915,
            entry_liquidity_score=0.544041,
            entry_net_expected_edge_bps=42.138166,
            entry_estimated_round_trip_cost_bps=8.772181,
            entry_planned_leverage=8,
        )

        payload = position.as_dict()

        self.assertEqual(payload["entry_price"], 0.0000038851)
        self.assertEqual(payload["current_price"], 0.0000038827)
        self.assertEqual(payload["active_stop_price"], 0.0000037769)
        self.assertEqual(payload["best_price"], 0.000003887)
        self.assertEqual(payload["worst_price"], 0.0000038802)
        self.assertNotEqual(payload["entry_price"], 0.000004)

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

    def test_paper_verify_kill_switch_keeps_decisions_but_blocks_new_submissions(self) -> None:
        session = self._build_session()
        decision_time = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_update_time = decision_time
        state.top_of_book = replace(state.top_of_book, updated_at=decision_time)
        session.runtime.paper_service.run_cycle = Mock(
            return_value=make_decision(
                timestamp=decision_time,
                side="long",
                net_expected_edge_bps=25.0,
                order_intent_notional_usd=1000.0,
            )
        )
        session.runtime.kill_switch.arm("DAILY_REALIZED_LOSS_LIMIT")
        session.next_scheduled_decision_at = decision_time

        with tempfile.TemporaryDirectory() as tmpdir:
            session.log_store = JsonlLogStore(Path(tmpdir))
            with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
                session._maybe_run_scheduled_decision_cycle(decision_time)

            preflight_rows = session.log_store.read("execution_preflight")

        self.assertEqual(len(session.decisions), 1)
        self.assertEqual(len(session.tested_orders), 0)
        self.assertEqual(session.paper_positions, {})
        self.assertEqual(preflight_rows[-1]["allow_new_submission"], False)
        self.assertEqual(preflight_rows[-1]["kill_switch_armed"], True)
        self.assertIn("DAILY_REALIZED_LOSS_LIMIT", preflight_rows[-1]["kill_switch_reasons"])
        self.assertGreater(session.next_scheduled_decision_at, decision_time)

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
    def test_session_keeps_short_hard_stop_loss_when_long_only_turnaround_enabled(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []

            def get_positions(self) -> dict[str, object]:
                return {
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "holdSide": "short",
                            "total": "0.02",
                            "available": "0.02",
                            "marginSize": "10",
                            "unrealizedPL": "-1.1",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1234568901",
                            "cTime": "1234568901",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "short-stop-loss"}

        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=True,
                long_disable_standard_stop_loss=True,
                stop_loss_roe_percent=-10.0,
                soft_stop_roe_percent=-8.0,
                turnaround_abort_roe_percent=-14.0,
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

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_STOP_LOSS")
        self.assertEqual(session.live_orders[0]["response"]["orderId"], "short-stop-loss")

    @patch("quant_binance.session.send_telegram_message")
    def test_session_skips_long_hard_and_soft_stop_with_long_turnaround_mode(self, mock_send) -> None:
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
                            "unrealizedPL": "-1.1",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1234568902",
                            "cTime": "1234568902",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "long-soft-stop"}

        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=True,
                long_disable_standard_stop_loss=True,
                stop_loss_roe_percent=-10.0,
                soft_stop_roe_percent=-8.0,
                turnaround_abort_roe_percent=-14.0,
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

        session.sync_account()

        self.assertEqual(len(session.live_orders), 0)
        self.assertEqual(len(session.rest_client.placed_orders), 0)

    @patch("quant_binance.session.send_telegram_message")
    def test_session_extends_long_turnaround_abort_under_high_volatility(self, mock_send) -> None:
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
                            "unrealizedPL": "-2.2",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1234568904",
                            "cTime": "1234568904",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "unexpected-close"}

        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=True,
                long_disable_standard_stop_loss=True,
                stop_loss_roe_percent=-10.0,
                soft_stop_roe_percent=-8.0,
                turnaround_abort_roe_percent=-20.0,
                turnaround_abort_volatility_adaptive=True,
                turnaround_abort_volatility_floor_bps=20.0,
                turnaround_abort_volatility_scale=0.2,
                turnaround_abort_volatility_lookback_bars=6,
                turnaround_abort_min_roe_percent=-35.0,
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
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        base_time = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        closes = [50000.0, 50500.0, 49500.0, 51000.0, 49000.0, 51500.0, 50000.0]
        bars: list[KlineBar] = []
        for index, close in enumerate(closes):
            bars.append(
                KlineBar(
                    symbol="BTCUSDT",
                    interval="1m",
                    start_time=base_time + timedelta(minutes=index),
                    close_time=base_time + timedelta(minutes=index + 1),
                    open_price=close,
                    high_price=close,
                    low_price=close,
                    close_price=close,
                    volume=1.0,
                    quote_volume=close,
                    is_closed=True,
                )
            )
        state.klines["1m"] = bars

        session.sync_account()

        self.assertEqual(len(session.live_orders), 0)
        self.assertEqual(len(session.rest_client.placed_orders), 0)

    @patch("quant_binance.session.send_telegram_message")
    def test_session_uses_max_interval_volatility_for_long_turnaround_abort(self, mock_send) -> None:
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
                            "unrealizedPL": "-2.2",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1234568905",
                            "cTime": "1234568905",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "unexpected-close"}

        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=True,
                long_disable_standard_stop_loss=True,
                stop_loss_roe_percent=-10.0,
                soft_stop_roe_percent=-8.0,
                turnaround_abort_roe_percent=-20.0,
                turnaround_abort_volatility_adaptive=True,
                turnaround_abort_volatility_floor_bps=20.0,
                turnaround_abort_volatility_scale=0.2,
                turnaround_abort_volatility_lookback_bars=6,
                turnaround_abort_min_roe_percent=-35.0,
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
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        base_time = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        # Low 1m volatility (< floor), by itself would keep abort near -20%.
        one_min_closes = [50000.0, 50010.0, 50005.0, 50012.0, 50008.0, 50011.0, 50009.0]
        one_min_bars: list[KlineBar] = []
        for index, close in enumerate(one_min_closes):
            one_min_bars.append(
                KlineBar(
                    symbol="BTCUSDT",
                    interval="1m",
                    start_time=base_time + timedelta(minutes=index),
                    close_time=base_time + timedelta(minutes=index + 1),
                    open_price=close,
                    high_price=close,
                    low_price=close,
                    close_price=close,
                    volume=1.0,
                    quote_volume=close,
                    is_closed=True,
                )
            )
        # Higher 5m volatility (> floor) should widen abort if max interval is used.
        five_min_closes = [50000.0, 52000.0, 49500.0, 53000.0, 50000.0, 52500.0, 50500.0]
        five_min_bars: list[KlineBar] = []
        for index, close in enumerate(five_min_closes):
            five_min_bars.append(
                KlineBar(
                    symbol="BTCUSDT",
                    interval="5m",
                    start_time=base_time + timedelta(minutes=index * 5),
                    close_time=base_time + timedelta(minutes=(index + 1) * 5),
                    open_price=close,
                    high_price=close,
                    low_price=close,
                    close_price=close,
                    volume=1.0,
                    quote_volume=close,
                    is_closed=True,
                )
            )
        state.klines["1m"] = one_min_bars
        state.klines["5m"] = five_min_bars

        session.sync_account()

        self.assertEqual(len(session.live_orders), 0)
        self.assertEqual(len(session.rest_client.placed_orders), 0)

    @patch("quant_binance.session.send_telegram_message")
    def test_session_uses_effective_long_abort_floor_for_turnaround_grace_window(self, mock_send) -> None:
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
                            "unrealizedPL": "-2.2",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1234568906",
                            "cTime": "1234568906",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "unexpected-close"}

        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=True,
                long_disable_standard_stop_loss=False,
                stop_loss_roe_percent=-30.0,
                soft_stop_roe_percent=-8.0,
                turnaround_abort_roe_percent=-20.0,
                turnaround_grace_enabled=True,
                turnaround_predictability_min=40.0,
                turnaround_liquidity_min=0.3,
                turnaround_net_edge_min_bps=-5.0,
                turnaround_recovery_roe_points=2.0,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=settings)
        session.rest_client = PositionRestClient()
        session.paper_positions["BTCUSDT"] = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="long",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            entry_price=50000.0,
            current_price=48900.0,
            quantity_opened=0.02,
            quantity_remaining=0.02,
            stop_distance_bps=500.0,
            active_stop_price=49500.0,
            best_price=50000.0,
            worst_price=48900.0,
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
        session.live_worst_roe_by_identity["BTCUSDT|long|1234568906"] = -26.0
        session._effective_long_turnaround_abort_roe_percent = lambda **kwargs: -30.0  # type: ignore[method-assign]

        session.sync_account()

        self.assertEqual(len(session.live_orders), 0)
        self.assertEqual(len(session.rest_client.placed_orders), 0)

    @patch("quant_binance.session.send_telegram_message")
    def test_session_forces_long_turnaround_abort_before_grace_paths(self, mock_send) -> None:
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
                            "unrealizedPL": "-1.5",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1234568903",
                            "cTime": "1234568903",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "long-turnaround-abort"}

        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=True,
                long_disable_standard_stop_loss=True,
                stop_loss_roe_percent=-10.0,
                soft_stop_roe_percent=-8.0,
                turnaround_abort_roe_percent=-14.0,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=settings)
        session.rest_client = PositionRestClient()

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_LONG_TURNAROUND_ABORT")
        self.assertEqual(session.live_orders[0]["response"]["orderId"], "long-turnaround-abort")

    @patch("quant_binance.session.send_telegram_message")
    def test_full_live_close_records_strategy_reason_without_manual_close_sync(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "strategy-close-1"}

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()
        entry_time = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        session.paper_positions["BTCUSDT"] = PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="long",
            entry_time=entry_time,
            entry_price=100.0,
            current_price=99.0,
            quantity_opened=1.0,
            quantity_remaining=1.0,
            stop_distance_bps=500.0,
            active_stop_price=95.0,
            best_price=101.0,
            worst_price=99.0,
            entry_predictability_score=82.0,
            entry_liquidity_score=0.8,
            entry_net_expected_edge_bps=18.0,
            entry_estimated_round_trip_cost_bps=8.0,
            entry_planned_leverage=30,
            exchange_synced=True,
        )

        session._close_live_position(
            position={
                "symbol": "BTCUSDT",
                "holdSide": "long",
                "total": "1",
                "available": "1",
                "markPrice": "99",
                "openPriceAvg": "100",
                "uTime": "1234568903",
                "cTime": "1234568903",
            },
            reason="LIVE_POSITION_LONG_TURNAROUND_ABORT",
        )

        self.assertNotIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.closed_trades[-1]["exit_reason"], "LIVE_POSITION_LONG_TURNAROUND_ABORT")
        self.assertNotEqual(session.closed_trades[-1]["exit_reason"], "MANUAL_CLOSE_SYNCED")

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
            universe=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
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
    def test_session_uses_short_specific_profit_protection_thresholds(self, mock_send) -> None:
        custom_settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_profit_protection_arm_roe_percent=99.0,
                major_profit_protection_retrace_roe_percent=99.0,
                short_profit_protection_arm_roe_percent=10.0,
                short_profit_protection_retrace_roe_percent=2.0,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=custom_settings)

        arm_threshold, retrace_threshold = session._live_profit_protection_thresholds(
            hold_side="short",
            is_major_symbol=True,
        )
        self.assertEqual(arm_threshold, 10.0)
        self.assertEqual(retrace_threshold, 2.0)
        self.assertTrue(
            session._profit_protection_partial_triggered(
                peak_roe_percent=12.0,
                current_roe_percent=9.0,
                retrace_taken=False,
                arm_threshold=arm_threshold,
                retrace_threshold=retrace_threshold,
            )
        )
        self.assertFalse(
            session._profit_protection_partial_triggered(
                peak_roe_percent=11.0,
                current_roe_percent=9.5,
                retrace_taken=False,
                arm_threshold=arm_threshold,
                retrace_threshold=retrace_threshold,
            )
        )

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
    def test_session_turnaround_grace_rejects_low_volume_trend_when_available(self, mock_send) -> None:
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
                            "unrealizedPL": "-1.1",
                            "marginRatio": "0.1",
                            "breakEvenPrice": "50000.0",
                            "openPriceAvg": "50000.0",
                            "uTime": "1234567899",
                            "cTime": "1234567899",
                        }
                    ]
                }

            def build_order_params(self, **kwargs):  # type: ignore[no-untyped-def]
                return kwargs

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, order_params))
                return {"status": "SUCCESS", "orderId": "soft-stop-close"}

        mock_send.return_value = {"ok": True}
        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                disable_standard_stop_loss_exits=False,
                long_only_turnaround_mode=False,
                long_disable_standard_stop_loss=False,
                soft_stop_roe_percent=-8.0,
                turnaround_abort_roe_percent=-20.0,
                turnaround_predictability_min=55.0,
                turnaround_net_edge_min_bps=2.0,
                turnaround_liquidity_min=0.45,
                turnaround_volume_confirmation_min=0.4,
                turnaround_trend_strength_min=0.55,
                major_drawdown_grace_enabled=False,
            ),
        )
        session = self._build_session(settings=settings)
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
            latest_volume_confirmation=0.2,
            latest_trend_strength=0.3,
            latest_decision_time=datetime.now(tz=timezone.utc),
            entry_net_expected_edge_bps=12.0,
            entry_estimated_round_trip_cost_bps=6.0,
            entry_planned_leverage=5,
        )
        session.live_worst_roe_by_identity["BTCUSDT|long|1234567899"] = -13.5

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_SOFT_STOP_LOSS")
        self.assertEqual(session.live_orders[0]["response"]["orderId"], "soft-stop-close")

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
    def test_session_uses_long_only_turnaround_rebound_threshold_and_fraction(self, mock_send) -> None:
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
                                "unrealizedPL": "-1.2",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "openPriceAvg": "50000.0",
                                "uTime": "1234567899",
                                "cTime": "1234567899",
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
                                "unrealizedPL": "0.12",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "openPriceAvg": "50000.0",
                                "uTime": "1234567899",
                                "cTime": "1234567899",
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
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "long-rebound-take-profit"}

        settings = replace(
            self.settings,
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=True,
                long_disable_standard_stop_loss=True,
                profit_flip_fast_take_profit_roe_percent=1.0,
                profit_flip_take_profit_fraction=0.5,
                turnaround_abort_roe_percent=-14.0,
                soft_stop_roe_percent=-8.0,
                take_profit_roe_percent=99.0,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=settings)
        session.rest_client = PositionRestClient()
        session.paper_positions["BTCUSDT"] = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="long",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            entry_price=50000.0,
            current_price=49400.0,
            quantity_opened=0.02,
            quantity_remaining=0.02,
            stop_distance_bps=500.0,
            active_stop_price=49500.0,
            best_price=50000.0,
            worst_price=49400.0,
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
        session.live_worst_roe_by_identity["BTCUSDT|long|1234567899"] = -14.5

        session.sync_account()
        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_TURNAROUND_TAKE_PROFIT")
        self.assertTrue(session.live_orders[0]["partial_exit"])
        self.assertAlmostEqual(float(session.live_orders[0]["quantity"]), 0.01, places=8)

    @patch("quant_binance.session.send_telegram_message")
    def test_session_uses_short_turnaround_rebound_threshold_and_full_exit(self, mock_send) -> None:
        class PositionRestClient(FakeRestClient):
            def __init__(self) -> None:
                super().__init__()
                self.placed_orders = []
                self.snapshots = [
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "short",
                                "total": "0.02",
                                "available": "0.02",
                                "marginSize": "10",
                                "unrealizedPL": "-0.9",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "openPriceAvg": "50000.0",
                                "uTime": "1234567898",
                                "cTime": "1234567898",
                            }
                        ]
                    },
                    {
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "holdSide": "short",
                                "total": "0.02",
                                "available": "0.02",
                                "marginSize": "10",
                                "unrealizedPL": "0.2",
                                "marginRatio": "0.1",
                                "breakEvenPrice": "50000.0",
                                "openPriceAvg": "50000.0",
                                "uTime": "1234567898",
                                "cTime": "1234567898",
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
                self.placed_orders.append((market, dict(order_params)))
                return {"status": "SUCCESS", "orderId": "short-rebound-take-profit"}

        settings = replace(
            self.settings,
            universe=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT",),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=True,
                long_disable_standard_stop_loss=True,
                short_profit_flip_fast_take_profit_roe_percent=1.5,
                short_profit_flip_take_profit_fraction=1.0,
                turnaround_abort_roe_percent=-14.0,
                soft_stop_roe_percent=-8.0,
                stop_loss_roe_percent=-20.0,
                take_profit_roe_percent=99.0,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(settings=settings)
        session.rest_client = PositionRestClient()
        session.paper_positions["BTCUSDT"] = __import__("quant_binance.session", fromlist=["PaperPosition"]).PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="short",
            entry_time=datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
            entry_price=50000.0,
            current_price=50600.0,
            quantity_opened=0.02,
            quantity_remaining=0.02,
            stop_distance_bps=500.0,
            active_stop_price=50500.0,
            best_price=50000.0,
            worst_price=50600.0,
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
        session.live_worst_roe_by_identity["BTCUSDT|short|1234567898"] = -9.5

        session.sync_account()
        session.sync_account()

        matching_orders = [order for order in session.live_orders if order["reason"] == "LIVE_POSITION_TURNAROUND_TAKE_PROFIT"]
        self.assertTrue(matching_orders)
        self.assertFalse(matching_orders[-1]["partial_exit"])
        self.assertAlmostEqual(float(matching_orders[-1]["quantity"]), 0.02, places=8)

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

    def test_session_delays_fee_negative_confirmation_exit_when_gross_is_positive(self) -> None:
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
        session._record_decision(
            decision=replace(pending_entry, divergence_code="ENTRY_CONFIRMATION_REQUIRED"),
            state=state,
            timestamp=entry_time,
        )

        fail_time = entry_time + timedelta(minutes=5)
        state.last_trade_price = 100.02
        session._record_decision(
            decision=make_decision(
                timestamp=fail_time,
                symbol="BTCUSDT",
                final_mode="cash",
                side="flat",
                predictability_score=45.0,
                liquidity_score=0.3,
                net_expected_edge_bps=-1.0,
                order_intent_notional_usd=0.0,
            ),
            state=state,
            timestamp=fail_time,
        )

        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(len(session.closed_trades), 0)

    def test_symbol_profile_liquidity_collapse_overrides_fee_negative_confirmation_delay(self) -> None:
        settings = replace(
            self.settings,
            symbol_filter_profiles={
                "PEPEUSDT": SymbolFilterProfileConfig(min_liquidity_score=0.55),
            },
        )
        session = self._build_session(settings=settings)
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state = replace(state, symbol="PEPEUSDT", last_trade_price=0.0000038841)
        session.runtime.dispatcher.store.put(state)

        entry_time = datetime(2026, 4, 22, 6, 55, tzinfo=timezone.utc)
        pending_entry = make_decision(
            timestamp=entry_time,
            symbol="PEPEUSDT",
            final_mode="futures",
            side="long",
            predictability_score=74.98,
            liquidity_score=0.5729,
            net_expected_edge_bps=39.45,
            estimated_round_trip_cost_bps=8.77,
            order_intent_notional_usd=200.0,
        )
        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            session._record_decision(
                decision=replace(pending_entry, divergence_code="ENTRY_CONFIRMATION_REQUIRED"),
                state=state,
                timestamp=entry_time,
            )

            fail_time = entry_time + timedelta(minutes=5)
            state.last_trade_price = 0.0000038850
            session._record_decision(
                decision=make_decision(
                    timestamp=fail_time,
                    symbol="PEPEUSDT",
                    final_mode="cash",
                    side="flat",
                    predictability_score=69.68,
                    liquidity_score=0.4379,
                    net_expected_edge_bps=20.12,
                    estimated_round_trip_cost_bps=15.72,
                    order_intent_notional_usd=0.0,
                ),
                state=state,
                timestamp=fail_time,
            )

        self.assertNotIn("PEPEUSDT", session.paper_positions)
        self.assertEqual(session.closed_trades[-1]["exit_reason"], "ENTRY_CONFIRMATION_FAILED")

    def test_paper_verification_restores_paper_only_open_position_without_exchange_position(self) -> None:
        session = self._build_session()
        entry_time = datetime(2026, 4, 22, 6, 55, tzinfo=timezone.utc)
        persisted = PaperPosition(
            symbol="PEPEUSDT",
            market="futures",
            side="long",
            entry_time=entry_time,
            entry_price=0.0000038841,
            current_price=0.0000038850,
            quantity_opened=51491980.12409568,
            quantity_remaining=51491980.12409568,
            stop_distance_bps=278.424492,
            active_stop_price=0.000003775957,
            best_price=0.0000038850,
            worst_price=0.0000038841,
            entry_predictability_score=74.98349,
            entry_liquidity_score=0.572929,
            entry_net_expected_edge_bps=39.44549,
            entry_estimated_round_trip_cost_bps=8.77238,
            entry_planned_leverage=8,
            confirmation_pending=True,
            confirmation_pending_since=entry_time,
        )

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            restored = session.restore_futures_state_from_runtime(
                state_payload={"paper_open_futures_positions": [persisted.as_dict()]},
                summary_payload={},
            )

        self.assertEqual(restored, 1)
        self.assertIn("PEPEUSDT", session.paper_positions)
        self.assertTrue(session.paper_positions["PEPEUSDT"].confirmation_pending)
        self.assertAlmostEqual(session.paper_positions["PEPEUSDT"].entry_price, 0.0000038841)

    def test_paper_verify_fee_drag_loss_guard_closes_eroded_futures_position(self) -> None:
        session = self._build_session()
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        session.paper_positions["BTCUSDT"] = PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="long",
            entry_time=now - timedelta(minutes=3),
            entry_price=100.0,
            current_price=100.0,
            quantity_opened=10.0,
            quantity_remaining=10.0,
            stop_distance_bps=500.0,
            active_stop_price=95.0,
            best_price=100.2,
            worst_price=99.8,
            entry_predictability_score=72.0,
            entry_liquidity_score=0.6,
            entry_net_expected_edge_bps=30.0,
            entry_estimated_round_trip_cost_bps=8.0,
            latest_predictability_score=65.0,
            latest_liquidity_score=0.5,
            latest_net_expected_edge_bps=18.0,
            latest_estimated_round_trip_cost_bps=12.0,
            latest_decision_time=now - timedelta(minutes=1),
        )
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_trade_price = 99.8

        with tempfile.TemporaryDirectory() as tmpdir:
            session.log_store = JsonlLogStore(Path(tmpdir))
            with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
                session._record_decision(
                    decision=make_decision(
                        timestamp=now,
                        symbol="BTCUSDT",
                        final_mode="futures",
                        side="long",
                        predictability_score=65.0,
                        liquidity_score=0.5,
                        net_expected_edge_bps=18.0,
                        estimated_round_trip_cost_bps=12.0,
                        order_intent_notional_usd=1000.0,
                    ),
                    state=state,
                    timestamp=now,
                )

            gate_rows = session.log_store.read("position_management_gate")
            preflight_rows = session.log_store.read("execution_preflight")

        self.assertNotIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.closed_trades[-1]["exit_reason"], "PAPER_VERIFY_FEE_DRAG_LOSS_GUARD")
        self.assertEqual(session.closed_trades[-1]["risk_limit_evaluation"], "skipped_paper_verification")
        self.assertFalse(session.runtime.kill_switch.armed)
        self.assertIn("PAPER_VERIFY_FEE_DRAG_LOSS_GUARD", gate_rows[-1]["reasons"])
        self.assertTrue(gate_rows[-1]["closed_during_management"])
        self.assertEqual(preflight_rows[-1]["position_close_reason"], "PAPER_VERIFY_FEE_DRAG_LOSS_GUARD")

    def test_paper_verify_aplus_full_size_locks_profit_before_fee_drag_reversal(self) -> None:
        settings = replace(
            self.settings,
            exit_rules=replace(
                self.settings.exit_rules,
                futures_proactive_take_profit_roe_thresholds_percent=(5.0, 18.0, 35.0),
                futures_proactive_take_profit_min_roe_percent=5.0,
                futures_proactive_take_profit_fraction=0.75,
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_partial_exit_fraction=0.75,
            ),
        )
        session = self._build_session(settings=settings)
        now = datetime(2026, 4, 21, 4, 30, tzinfo=timezone.utc)
        session.paper_positions["BTCUSDT"] = PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="long",
            entry_time=now - timedelta(minutes=4),
            entry_price=100.0,
            current_price=100.0,
            quantity_opened=14.25,
            quantity_remaining=14.25,
            stop_distance_bps=350.0,
            active_stop_price=96.5,
            best_price=100.0,
            worst_price=100.0,
            entry_predictability_score=81.0,
            entry_liquidity_score=0.98,
            entry_net_expected_edge_bps=40.0,
            entry_estimated_round_trip_cost_bps=6.6,
            entry_planned_leverage=30,
            latest_predictability_score=81.0,
            latest_liquidity_score=0.98,
            latest_net_expected_edge_bps=40.0,
            latest_estimated_round_trip_cost_bps=6.6,
            latest_decision_time=now - timedelta(minutes=1),
        )
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_trade_price = 100.2

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            session._record_decision(
                decision=make_decision(
                    timestamp=now,
                    symbol="BTCUSDT",
                    final_mode="futures",
                    side="long",
                    predictability_score=81.0,
                    liquidity_score=0.98,
                    net_expected_edge_bps=40.0,
                    estimated_round_trip_cost_bps=6.6,
                    order_intent_notional_usd=1425.0,
                ),
                state=state,
                timestamp=now,
            )

        position = session.paper_positions["BTCUSDT"]
        self.assertEqual(session.closed_trades[-1]["exit_reason"], "PROACTIVE_PARTIAL_TAKE_PROFIT")
        self.assertTrue(position.partial_take_profit_taken)
        self.assertEqual(position.proactive_take_profit_thresholds_hit, (5.0,))
        self.assertAlmostEqual(position.quantity_remaining, position.quantity_opened * 0.25)
        self.assertEqual(position.active_stop_price, position.entry_price)

        state.last_trade_price = 100.0
        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            session._record_decision(
                decision=make_decision(
                    timestamp=now + timedelta(minutes=1),
                    symbol="BTCUSDT",
                    final_mode="futures",
                    side="long",
                    predictability_score=73.0,
                    liquidity_score=0.6,
                    net_expected_edge_bps=22.0,
                    estimated_round_trip_cost_bps=6.6,
                    order_intent_notional_usd=0.0,
                ),
                state=state,
                timestamp=now + timedelta(minutes=1),
            )

        self.assertNotIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.closed_trades[-1]["exit_reason"], "BREAKEVEN_STOP")
        total_net = sum(float(trade["realized_pnl_net_usd_estimate"]) for trade in session.closed_trades)
        self.assertGreater(total_net, 0.0)

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
            universe=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
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
        self.assertEqual(len(session.closed_trades), 0)
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
        self.assertTrue(session.paper_positions["BTCUSDT"].exchange_synced)

    def test_live_entry_exchange_synced_paper_position_survives_reversal_signal(self) -> None:
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
        entry_time = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        state.last_trade_price = 100.0

        session._record_decision(
            decision=make_decision(timestamp=entry_time, symbol="BTCUSDT", side="long"),
            state=state,
            timestamp=entry_time,
        )
        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertTrue(session.paper_positions["BTCUSDT"].exchange_synced)

        reversal_time = entry_time + timedelta(minutes=5)
        session._record_decision(
            decision=make_decision(timestamp=reversal_time, symbol="BTCUSDT", side="short"),
            state=state,
            timestamp=reversal_time,
        )

        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.paper_positions["BTCUSDT"].side, "long")
        self.assertEqual(len(session.closed_trades), 0)

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

    def test_preflight_symbol_cooldown_does_not_slide_while_active(self) -> None:
        session = self._build_session()
        first = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        session._apply_preflight_symbol_cooldown(symbol="BTCUSDT", timestamp=first, seconds=120)

        self.assertEqual(
            session.manual_symbol_cooldowns["BTCUSDT"],
            first + timedelta(seconds=120),
        )

        second = first + timedelta(seconds=30)
        session._apply_preflight_symbol_cooldown(symbol="BTCUSDT", timestamp=second, seconds=120)

        self.assertEqual(
            session.manual_symbol_cooldowns["BTCUSDT"],
            first + timedelta(seconds=120),
        )

    def test_cleanup_missing_on_exchange_position_does_not_slide_active_manual_cooldown(self) -> None:
        session = self._build_session()
        first = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
        session.manual_symbol_cooldowns["BTCUSDT"] = first + timedelta(minutes=5)

        session._cleanup_missing_on_exchange_position(
            symbol="BTCUSDT",
            now=first + timedelta(minutes=1),
            reason="MANUAL_CLOSE_SYNCED",
        )

        self.assertEqual(
            session.manual_symbol_cooldowns["BTCUSDT"],
            first + timedelta(minutes=5),
        )

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

    def test_major_futures_liquidity_drop_exit_applies_symbol_specific_reentry_cooldown(self) -> None:
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
            latest_liquidity_score=0.45,
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
            exit_reason="LIQUIDITY_DROP_EXIT",
        )

        self.assertEqual(
            session.manual_symbol_cooldowns["BTCUSDT"],
            now + timedelta(minutes=40),
        )

    def test_major_futures_breakeven_after_partial_profit_applies_reentry_cooldown(self) -> None:
        settings = replace(
            self.settings,
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                major_reentry_cooldown_minutes=480,
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
            current_price=100.0,
            quantity_opened=1.0,
            quantity_remaining=0.5,
            stop_distance_bps=500.0,
            active_stop_price=100.0,
            best_price=108.0,
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
            partial_take_profit_taken=True,
        )

        session._close_position(
            position=position,
            exit_price=100.0,
            timestamp=now,
            exit_reason="BREAKEVEN_STOP",
        )

        self.assertEqual(
            session.manual_symbol_cooldowns["BTCUSDT"],
            now + timedelta(minutes=480),
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
        state.last_trade_price = 100.2
        session._record_decision(
            decision=make_decision(timestamp=follow_time, order_intent_notional_usd=1400.0),
            state=state,
            timestamp=follow_time,
        )

        self.assertEqual(len(session.paper_positions), 1)
        self.assertEqual(len(session.closed_trades), 0)
        self.assertEqual(len(session.tested_orders), 1)

    def test_paper_verification_reversal_closes_and_reopens_simulated_position(self) -> None:
        session = self._build_session()
        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        entry_time = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        session.paper_positions["BTCUSDT"] = PaperPosition(
            symbol="BTCUSDT",
            market="futures",
            side="short",
            entry_time=entry_time,
            entry_price=100.0,
            current_price=100.0,
            quantity_opened=10.0,
            quantity_remaining=10.0,
            stop_distance_bps=500.0,
            active_stop_price=105.0,
            best_price=100.0,
            worst_price=100.0,
            entry_predictability_score=82.0,
            entry_liquidity_score=0.8,
            entry_net_expected_edge_bps=28.0,
            entry_estimated_round_trip_cost_bps=10.0,
            entry_planned_leverage=30,
        )

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            reverse_time = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
            state.last_trade_price = 100.2
            session._record_decision(
                decision=make_decision(
                    timestamp=reverse_time,
                    side="long",
                    gross_expected_edge_bps=38.0,
                    net_expected_edge_bps=28.0,
                    order_intent_notional_usd=1000.0,
                ),
                state=state,
                timestamp=reverse_time,
            )

        self.assertEqual(len(session.closed_trades), 1)
        self.assertEqual(session.closed_trades[0]["exit_reason"], "PAPER_VERIFY_SIGNAL_REVERSAL")
        self.assertEqual(len(session.tested_orders), 1)
        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.paper_positions["BTCUSDT"].side, "long")
        self.assertEqual(len(session.live_orders), 0)

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
        self.assertEqual(len(session.closed_trades), 0)
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

    def test_paper_verify_reallocation_requires_incremental_pnl_to_clear_switching_fees(self) -> None:
        settings = replace(
            self._focus_settings(futures_top_n=1),
            portfolio_focus=replace(
                self._focus_settings(futures_top_n=1).portfolio_focus,
                min_incremental_pnl_usd=0.0,
            ),
        )
        with tempfile.TemporaryDirectory() as tempdir:
            session = self._build_session(settings=settings)
            session.log_store = JsonlLogStore(tempdir)
            now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
            self._seed_weak_futures_position(
                session,
                symbol="ETHUSDT",
                entry_time=now - timedelta(minutes=10),
                entry_price=2315.14,
                current_price=2315.45,
                quantity=0.45353629,
                latest_predictability_score=63.72,
                latest_net_expected_edge_bps=-19.24,
                latest_estimated_round_trip_cost_bps=20.13,
            )
            session.capital_report = {
                "futures_available_balance_usd": 50.0,
                "futures_execution_balance_usd": 15.0,
                "can_trade_futures_any": True,
                "futures_requirements": [
                    {"symbol": "SOLUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                ],
            }
            state = session.runtime.dispatcher.store.get("BTCUSDT")
            assert state is not None
            state.last_trade_price = 85.287

            with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
                managed = session._maybe_reallocate_futures_entry(
                    decision=make_decision(
                        timestamp=now,
                        symbol="SOLUSDT",
                        predictability_score=94.0,
                        gross_expected_edge_bps=37.0,
                        net_expected_edge_bps=27.0,
                        estimated_round_trip_cost_bps=11.92,
                        order_intent_notional_usd=450.0,
                    ),
                    state=state,
                    timestamp=now,
                )

            self.assertEqual(managed.final_mode, "cash")
            self.assertIn("MAX_CONCURRENT_FUTURES", managed.rejection_reasons)
            self.assertEqual(len(session.closed_trades), 0)
            events = session.log_store.read("futures_reallocation")
            self.assertEqual(events[-1]["skip_reason"], "INCREMENTAL_PNL_BELOW_FLOOR")

    def test_paper_verify_policy_mismatch_requires_fast_path_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = replace(
                self.settings,
                risk=replace(
                    self.settings.risk,
                    max_futures_leverage=30.0,
                    target_futures_leverage=30.0,
                ),
            )
            session = self._build_session(settings=settings)
            run_dir = Path(tempdir) / "output" / "paper-live-shell" / "run-a"
            run_dir.mkdir(parents=True, exist_ok=True)
            session.summary_path = run_dir / "summary.json"
            session.summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "policy_lineage": {
                            "available": True,
                            "structural_key": "mismatch-lineage",
                            "versioned_key": "mismatch-lineage-v1",
                        },
                        "policy_evidence_buckets": {
                            "active_policy": {
                                "available": False,
                                "source": "active_policy_live_evidence_pending",
                                "alignment": {"aligned": False, "status": "mismatch"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            session.capital_report = {
                "can_trade_futures_any": True,
                "futures_execution_balance_usd": 50.0,
                "futures_available_balance_usd": 50.0,
                "futures_requirements": [
                    {"symbol": "PEPEUSDT", "min_notional_usd": 5.0, "min_quantity": 1000.0},
                    {"symbol": "SOLUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                ],
            }
            weak_mismatch = replace(
                make_decision(
                    timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                    symbol="PEPEUSDT",
                    predictability_score=69.5,
                    liquidity_score=0.58,
                    gross_expected_edge_bps=30.0,
                    net_expected_edge_bps=21.9,
                    estimated_round_trip_cost_bps=8.3,
                    order_intent_notional_usd=486.0,
                ),
                volume_confirmation=0.41,
            )
            fast_path = replace(
                make_decision(
                    timestamp=datetime(2026, 3, 8, 12, 6, tzinfo=timezone.utc),
                    symbol="SOLUSDT",
                    predictability_score=76.0,
                    liquidity_score=0.62,
                    gross_expected_edge_bps=78.0,
                    net_expected_edge_bps=60.0,
                    estimated_round_trip_cost_bps=9.0,
                    order_intent_notional_usd=787.0,
                ),
                volume_confirmation=0.65,
            )

            with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
                blocked = session._cap_live_order_decision(weak_mismatch, reference_price=0.00000375)
                allowed = session._cap_live_order_decision(fast_path, reference_price=85.0)

        self.assertEqual(blocked.final_mode, "cash")
        self.assertIn("POLICY_ALIGNMENT_CONFIRMATION_REQUIRED", blocked.rejection_reasons)
        self.assertEqual(allowed.final_mode, "futures")
        self.assertNotIn("POLICY_ALIGNMENT_CONFIRMATION_REQUIRED", allowed.rejection_reasons)

    def test_paper_verify_policy_demote_blocks_even_elite_mismatch_fast_path(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = replace(
                self.settings,
                risk=replace(
                    self.settings.risk,
                    max_futures_leverage=30.0,
                    target_futures_leverage=30.0,
                ),
            )
            session = self._build_session(settings=settings)
            run_dir = Path(tempdir) / "output" / "paper-live-shell" / "run-a"
            run_dir.mkdir(parents=True, exist_ok=True)
            session.summary_path = run_dir / "summary.json"
            session.summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "policy_lineage": {
                            "available": True,
                            "policy_status": "demote",
                            "structural_key": "demoted-lineage",
                            "versioned_key": "demoted-lineage-v1",
                        },
                        "policy_evidence_buckets": {
                            "active_policy": {
                                "available": False,
                                "source": "active_policy_live_evidence_pending",
                                "alignment": {"aligned": False, "status": "mismatch"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            session.capital_report = {
                "can_trade_futures_any": True,
                "futures_execution_balance_usd": 50.0,
                "futures_available_balance_usd": 50.0,
                "futures_requirements": [
                    {"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                ],
            }
            demoted_elite = replace(
                make_decision(
                    timestamp=datetime(2026, 3, 8, 12, 6, tzinfo=timezone.utc),
                    symbol="ETHUSDT",
                    predictability_score=80.0,
                    liquidity_score=0.898,
                    gross_expected_edge_bps=82.0,
                    net_expected_edge_bps=40.0,
                    estimated_round_trip_cost_bps=6.0,
                    order_intent_notional_usd=787.0,
                ),
                volume_confirmation=0.65,
            )

            with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
                blocked = session._cap_live_order_decision(demoted_elite, reference_price=2300.0)

        self.assertEqual(blocked.final_mode, "cash")
        self.assertIn("POLICY_ALIGNMENT_DEMOTED_BUCKET", blocked.rejection_reasons)

    def test_policy_demote_does_not_block_unlisted_symbol_like_probe40_pepe(self) -> None:
        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                max_futures_leverage=30.0,
                target_futures_leverage=30.0,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [
                {"symbol": "PEPEUSDT", "min_notional_usd": 5.0, "min_quantity": 1.0},
            ],
        }
        pepe_elite = replace(
            make_decision(
                timestamp=datetime(2026, 4, 21, 8, 21, tzinfo=timezone.utc),
                symbol="PEPEUSDT",
                predictability_score=73.67,
                liquidity_score=0.561,
                gross_expected_edge_bps=47.0,
                net_expected_edge_bps=33.92,
                estimated_round_trip_cost_bps=13.1,
                order_intent_notional_usd=1500.0,
            ),
            trend_strength=0.727,
            volume_confirmation=0.743,
        )
        policy_context = {
            "entry_policy_context_source": "active_policy",
            "entry_policy_bucket": "active_policy",
            "entry_policy_bucket_available": False,
            "entry_policy_bucket_alignment_status": "pending",
            "entry_policy_lineage": {
                "available": True,
                "policy_status": "demote",
                "symbols": ["SOLUSDT"],
                "structural_key": "sol-demoted-lineage",
                "versioned_key": "sol-demoted-lineage-v1",
            },
        }

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            allowed = session._cap_live_order_decision(
                pepe_elite,
                reference_price=0.0000037831,
                policy_entry_context=policy_context,
            )

        self.assertEqual(allowed.final_mode, "futures")
        self.assertEqual(allowed.side, "long")
        self.assertNotIn("POLICY_ALIGNMENT_DEMOTED_BUCKET", allowed.rejection_reasons)

    def test_paper_verify_aligned_entry_requires_fee_buffer_when_microstructure_is_weak(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            session = self._build_session()
            run_dir = Path(tempdir) / "output" / "paper-live-shell" / "run-a"
            run_dir.mkdir(parents=True, exist_ok=True)
            session.summary_path = run_dir / "summary.json"
            session.summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "policy_lineage": {
                            "available": True,
                            "structural_key": "aligned-lineage",
                            "versioned_key": "aligned-lineage-v1",
                        },
                        "policy_evidence_buckets": {
                            "active_policy": {
                                "available": True,
                                "source": "observed_runtime_policy_bucket_artifacts",
                                "alignment": {"aligned": True, "status": "aligned"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            session.capital_report = {
                "can_trade_futures_any": True,
                "futures_execution_balance_usd": 50.0,
                "futures_available_balance_usd": 50.0,
                "futures_requirements": [
                    {"symbol": "PEPEUSDT", "min_notional_usd": 5.0, "min_quantity": 1000.0},
                    {"symbol": "SOLUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                ],
            }
            weak_buffer = replace(
                make_decision(
                    timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
                    symbol="PEPEUSDT",
                    predictability_score=67.8,
                    liquidity_score=0.538,
                    gross_expected_edge_bps=24.5,
                    net_expected_edge_bps=16.8,
                    estimated_round_trip_cost_bps=7.7,
                    order_intent_notional_usd=1015.0,
                ),
                volume_confirmation=0.50,
            )
            strong_buffer = replace(
                make_decision(
                    timestamp=datetime(2026, 3, 8, 12, 6, tzinfo=timezone.utc),
                    symbol="SOLUSDT",
                    predictability_score=72.0,
                    liquidity_score=0.576,
                    gross_expected_edge_bps=41.0,
                    net_expected_edge_bps=32.4,
                    estimated_round_trip_cost_bps=9.0,
                    order_intent_notional_usd=787.0,
                ),
                volume_confirmation=0.68,
            )

            with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
                blocked = session._cap_live_order_decision(weak_buffer, reference_price=0.00000376)
                allowed = session._cap_live_order_decision(strong_buffer, reference_price=85.0)

        self.assertEqual(blocked.final_mode, "cash")
        self.assertIn("FEE_EDGE_BUFFER_CONFIRMATION_REQUIRED", blocked.rejection_reasons)
        self.assertEqual(allowed.final_mode, "futures")
        self.assertNotIn("FEE_EDGE_BUFFER_CONFIRMATION_REQUIRED", allowed.rejection_reasons)

    def test_paper_verify_blocks_fragile_full_leverage_short_entry(self) -> None:
        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                max_futures_leverage=30.0,
                target_futures_leverage=30.0,
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=False,
            ),
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [
                {"symbol": "PEPEUSDT", "min_notional_usd": 5.0, "min_quantity": 1000.0},
            ],
        }
        fragile_short = replace(
            make_decision(
                timestamp=datetime(2026, 4, 22, 1, 25, tzinfo=timezone.utc),
                symbol="PEPEUSDT",
                side="short",
                predictability_score=72.3018,
                liquidity_score=0.538923,
                gross_expected_edge_bps=46.165268,
                net_expected_edge_bps=37.374421,
                estimated_round_trip_cost_bps=8.790847,
                order_intent_notional_usd=1500.0,
                stop_distance_bps=354.186594,
            ),
            volume_confirmation=0.561133,
            trend_strength=0.813067,
        )

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            capped = session._cap_live_order_decision(fragile_short, reference_price=0.0000037934)

        self.assertEqual(capped.final_mode, "cash")
        self.assertEqual(capped.side, "flat")
        self.assertIn("PAPER_VERIFY_FRAGILE_FEE_DRAG_ENTRY", capped.rejection_reasons)

    def test_paper_verify_allows_marginal_liquidity_strong_continuation_entry(self) -> None:
        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                max_futures_leverage=30.0,
                target_futures_leverage=30.0,
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=False,
            ),
            symbol_filter_profiles={
                "ETHUSDT": SymbolFilterProfileConfig(
                    reversal_prone_guard_enabled=True,
                    reversal_guard_marginal_score=75.0,
                    reversal_guard_marginal_trend_strength=0.70,
                    reversal_guard_marginal_volume_confirmation=0.58,
                    reversal_guard_min_net_edge_bps=30.0,
                    reversal_guard_min_edge_to_cost=3.25,
                    reversal_guard_min_expected_profit_multiplier=2.0,
                    reversal_guard_min_expected_profit_extra_usd=0.75,
                ),
            },
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [
                {"symbol": "PEPEUSDT", "min_notional_usd": 5.0, "min_quantity": 1000.0},
            ],
        }
        strong_continuation = replace(
            make_decision(
                timestamp=datetime(2026, 4, 22, 2, 35, tzinfo=timezone.utc),
                symbol="PEPEUSDT",
                side="long",
                predictability_score=70.711595,
                liquidity_score=0.538608,
                gross_expected_edge_bps=39.195934,
                net_expected_edge_bps=30.418994,
                estimated_round_trip_cost_bps=8.77694,
                order_intent_notional_usd=1500.0,
                stop_distance_bps=229.8,
            ),
            volume_confirmation=0.743405,
            trend_strength=0.808792,
        )

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            capped = session._cap_live_order_decision(strong_continuation, reference_price=0.0000038613)

        self.assertEqual(capped.final_mode, "futures")
        self.assertEqual(capped.side, "long")
        self.assertNotIn("PAPER_VERIFY_FRAGILE_FEE_DRAG_ENTRY", capped.rejection_reasons)
        self.assertNotIn("FEE_EDGE_BUFFER_CONFIRMATION_REQUIRED", capped.rejection_reasons)

    def test_paper_verify_blocks_unconfirmed_reversal_prone_major_entry(self) -> None:
        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                max_futures_leverage=30.0,
                target_futures_leverage=30.0,
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=False,
            ),
            symbol_filter_profiles={
                "BTCUSDT": SymbolFilterProfileConfig(
                    reversal_prone_guard_enabled=True,
                    reversal_guard_marginal_score=75.0,
                    reversal_guard_marginal_trend_strength=0.70,
                    reversal_guard_marginal_volume_confirmation=0.58,
                    reversal_guard_min_net_edge_bps=30.0,
                    reversal_guard_min_edge_to_cost=3.25,
                    reversal_guard_min_expected_profit_multiplier=2.0,
                    reversal_guard_min_expected_profit_extra_usd=0.75,
                ),
            },
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.00001},
            ],
        }
        reversal_prone = replace(
            make_decision(
                timestamp=datetime(2026, 4, 22, 3, 10, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                side="long",
                predictability_score=70.604535,
                liquidity_score=0.711646,
                gross_expected_edge_bps=32.148908,
                net_expected_edge_bps=24.145038,
                estimated_round_trip_cost_bps=8.00387,
                order_intent_notional_usd=225.0,
                stop_distance_bps=82.50608,
            ),
            volume_confirmation=0.555694,
            trend_strength=0.679367,
        )

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            capped = session._apply_fee_sensitive_entry_quality_buffer(reversal_prone)

        self.assertEqual(capped.final_mode, "cash")
        self.assertEqual(capped.side, "flat")
        self.assertIn("PAPER_VERIFY_REVERSAL_PRONE_ENTRY", capped.rejection_reasons)

    def test_reversal_prone_guard_is_symbol_profile_scoped(self) -> None:
        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                max_futures_leverage=30.0,
                target_futures_leverage=30.0,
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=False,
            ),
            symbol_filter_profiles={
                "ETHUSDT": SymbolFilterProfileConfig(
                    reversal_prone_guard_enabled=True,
                    reversal_guard_marginal_score=75.0,
                    reversal_guard_marginal_trend_strength=0.70,
                    reversal_guard_marginal_volume_confirmation=0.58,
                    reversal_guard_min_net_edge_bps=30.0,
                    reversal_guard_min_edge_to_cost=3.25,
                    reversal_guard_min_expected_profit_multiplier=2.0,
                    reversal_guard_min_expected_profit_extra_usd=0.75,
                ),
            },
        )
        session = self._build_session(settings=settings)
        reversal_prone = replace(
            make_decision(
                timestamp=datetime(2026, 4, 22, 3, 10, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                side="long",
                predictability_score=70.604535,
                liquidity_score=0.711646,
                gross_expected_edge_bps=32.148908,
                net_expected_edge_bps=24.145038,
                estimated_round_trip_cost_bps=8.00387,
                order_intent_notional_usd=225.0,
                stop_distance_bps=82.50608,
            ),
            volume_confirmation=0.555694,
            trend_strength=0.679367,
        )

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            capped = session._apply_fee_sensitive_entry_quality_buffer(reversal_prone)

        self.assertNotIn("PAPER_VERIFY_REVERSAL_PRONE_ENTRY", capped.rejection_reasons)

    def test_paper_verify_allows_high_conviction_reversal_entry_after_loss_guard(self) -> None:
        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                max_futures_leverage=30.0,
                target_futures_leverage=30.0,
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=False,
            ),
            symbol_filter_profiles={
                "BTCUSDT": SymbolFilterProfileConfig(
                    reversal_prone_guard_enabled=True,
                    reversal_guard_marginal_score=75.0,
                    reversal_guard_marginal_trend_strength=0.70,
                    reversal_guard_marginal_volume_confirmation=0.58,
                    reversal_guard_min_net_edge_bps=30.0,
                    reversal_guard_min_edge_to_cost=3.25,
                    reversal_guard_min_expected_profit_multiplier=2.0,
                    reversal_guard_min_expected_profit_extra_usd=0.75,
                ),
            },
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.00001},
            ],
        }
        high_conviction_short = replace(
            make_decision(
                timestamp=datetime(2026, 4, 22, 3, 20, tzinfo=timezone.utc),
                symbol="BTCUSDT",
                side="short",
                predictability_score=92.869715,
                liquidity_score=0.899408,
                gross_expected_edge_bps=61.535115,
                net_expected_edge_bps=53.496371,
                estimated_round_trip_cost_bps=8.038744,
                order_intent_notional_usd=225.0,
                stop_distance_bps=84.336194,
            ),
            volume_confirmation=0.807143,
            trend_strength=0.959286,
        )

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            capped = session._apply_fee_sensitive_entry_quality_buffer(high_conviction_short)

        self.assertEqual(capped.final_mode, "futures")
        self.assertEqual(capped.side, "short")
        self.assertNotIn("PAPER_VERIFY_REVERSAL_PRONE_ENTRY", capped.rejection_reasons)

    def test_symbol_filter_profiles_apply_distinct_coin_entry_gates(self) -> None:
        settings = replace(
            self.settings,
            risk=replace(
                self.settings.risk,
                max_futures_leverage=30.0,
                target_futures_leverage=30.0,
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=False,
            ),
            symbol_filter_profiles={
                "BTCUSDT": SymbolFilterProfileConfig(
                    min_predictability_score=68.0,
                    min_liquidity_score=0.48,
                    min_volume_confirmation=0.45,
                    min_net_edge_bps=18.0,
                    min_edge_to_cost=1.6,
                    max_stop_distance_bps=280.0,
                    min_expected_profit_multiplier=1.2,
                    bypass_fee_edge_buffer=True,
                ),
                "DOGEUSDT": SymbolFilterProfileConfig(
                    min_predictability_score=73.0,
                    min_liquidity_score=0.54,
                    min_volume_confirmation=0.58,
                    min_net_edge_bps=32.0,
                    min_edge_to_cost=3.0,
                    max_stop_distance_bps=240.0,
                    min_expected_profit_multiplier=1.6,
                ),
            },
        )
        session = self._build_session(settings=settings)
        session.capital_report = {
            "can_trade_futures_any": True,
            "futures_execution_balance_usd": 50.0,
            "futures_available_balance_usd": 50.0,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.00001},
                {"symbol": "DOGEUSDT", "min_notional_usd": 5.0, "min_quantity": 1.0},
            ],
        }
        btc_candidate = make_decision(
            timestamp=datetime(2026, 4, 22, 3, 0, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            predictability_score=76.0,
            liquidity_score=0.50,
            gross_expected_edge_bps=42.0,
            net_expected_edge_bps=32.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=750.0,
            stop_distance_bps=220.0,
        )
        doge_candidate = replace(
            make_decision(
                timestamp=datetime(2026, 4, 22, 3, 0, tzinfo=timezone.utc),
                symbol="DOGEUSDT",
                predictability_score=74.0,
                liquidity_score=0.55,
                gross_expected_edge_bps=36.0,
                net_expected_edge_bps=28.8,
                estimated_round_trip_cost_bps=11.1,
                order_intent_notional_usd=750.0,
                stop_distance_bps=220.0,
            ),
            volume_confirmation=0.60,
        )

        with patch.dict("os.environ", {"QUANT_PAPER_VERIFY_EQUITY_USD": "50"}, clear=False):
            btc_capped = session._cap_live_order_decision(btc_candidate, reference_price=77500.0)
            doge_capped = session._cap_live_order_decision(doge_candidate, reference_price=0.15)

        self.assertEqual(btc_capped.final_mode, "futures")
        self.assertEqual(btc_capped.side, "long")
        self.assertEqual(doge_capped.final_mode, "cash")
        self.assertIn("SYMBOL_PROFILE_EDGE_TOO_THIN", doge_capped.rejection_reasons)
        self.assertIn("SYMBOL_PROFILE_EDGE_COST_TOO_THIN", doge_capped.rejection_reasons)

    def test_futures_entry_uses_total_reusable_balance_when_execution_balance_is_low(self) -> None:
        from quant_binance.models import DecisionIntent

        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(MarketStateStore()),
            paper_service=PaperTradingService(self.settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
            decision_interval_seconds=self.settings.decision_engine.decision_interval_seconds,
        )
        session = LivePaperSession(runtime=runtime, equity_usd=10000.0, remaining_portfolio_capacity_usd=5000.0)
        session.capital_report = {
            "futures_available_balance_usd": 1.0,
            "futures_execution_balance_usd": 1.0,
            "futures_total_reusable_balance_usd": 120.0,
            "futures_recognized_balance_usd": 120.0,
            "can_trade_futures_any": True,
            "futures_requirements": [{"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001}],
        }
        decision = DecisionIntent(
            decision_id="d-reusable-balance",
            decision_hash="hash-reusable-balance",
            snapshot_id="s-reusable-balance",
            config_version="2026-03-21.v1",
            timestamp=datetime(2026, 3, 21, 4, 0, tzinfo=timezone.utc),
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
            order_intent_notional_usd=95.0,
            stop_distance_bps=45.0,
        )

        capped = session._cap_live_order_decision(decision, reference_price=2500.0)

        self.assertEqual(capped.final_mode, "futures")
        self.assertGreater(capped.order_intent_notional_usd, 0.0)
        self.assertNotIn("INSUFFICIENT_EXECUTION_BALANCE", capped.rejection_reasons)
        self.assertNotIn("FUTURES_COLLATERAL_AVAILABLE", capped.rejection_reasons)

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
            self.assertEqual(len(session.closed_trades), 0)
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

    def test_decision_and_closed_trade_logs_persist_entry_policy_lineage_without_inventing_manual_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            session = self._build_session()
            run_dir = Path(tempdir) / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            session.summary_path = run_dir / "summary.json"
            session.summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "policy_lineage": {
                            "available": True,
                            "structural_key": "active-lineage",
                            "versioned_key": "active-lineage-v1",
                        },
                        "rollout_progression": {"execution_phase": "partial"},
                        "policy_evidence_buckets": {
                            "active_policy": {
                                "available": True,
                                "source": "persisted_policy_validation_evidence",
                                "alignment": {"aligned": True, "status": "aligned", "reason": "POLICY_LINEAGE_MATCH"},
                                "policy_lineage": {
                                    "available": True,
                                    "structural_key": "active-lineage",
                                    "versioned_key": "active-lineage-v1",
                                },
                                "evidence": {"runner_avg_edge_retention_ratio": 0.82},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            session.log_store = JsonlLogStore(logs_dir)
            now = datetime(2026, 3, 19, 12, 0, tzinfo=timezone.utc)
            state = session.runtime.dispatcher.store.get("BTCUSDT")
            assert state is not None
            decision = make_decision(
                timestamp=now,
                symbol="BTCUSDT",
                predictability_score=91.0,
                gross_expected_edge_bps=22.0,
                net_expected_edge_bps=16.0,
                estimated_round_trip_cost_bps=6.0,
                order_intent_notional_usd=500.0,
            )

            session._record_decision(decision=decision, state=state, timestamp=now, bootstrap=True)
            decision_rows = session.log_store.read("decisions")
            self.assertEqual(len(decision_rows), 1)
            self.assertEqual(decision_rows[0]["entry_policy_context_source"], "active_policy")
            self.assertEqual(decision_rows[0]["entry_policy_bucket"], "active_policy")
            self.assertTrue(decision_rows[0]["entry_policy_bucket_available"])
            self.assertEqual(decision_rows[0]["entry_policy_bucket_source"], "persisted_policy_validation_evidence")
            self.assertEqual(decision_rows[0]["entry_policy_bucket_alignment_status"], "aligned")
            self.assertEqual(decision_rows[0]["entry_policy_execution_phase"], "partial")
            self.assertEqual(decision_rows[0]["entry_policy_lineage"]["structural_key"], "active-lineage")

            opened = session._open_paper_position(decision=decision, price=state.last_trade_price)
            self.assertTrue(opened)
            strategy_position = session.paper_positions["BTCUSDT"]
            session._record_closed_trade(
                position=strategy_position,
                exit_price=state.last_trade_price * 1.01,
                quantity_closed=strategy_position.quantity_remaining,
                exit_time=now + timedelta(minutes=5),
                exit_reason="TARGET",
            )
            manual_position = PaperPosition(
                symbol="ETHUSDT",
                market="futures",
                side="long",
                entry_time=now,
                entry_price=2500.0,
                current_price=2500.0,
                quantity_opened=1.0,
                quantity_remaining=1.0,
                stop_distance_bps=0.0,
                active_stop_price=2500.0,
                best_price=2500.0,
                worst_price=2500.0,
                entry_predictability_score=0.0,
                entry_liquidity_score=0.0,
                origin="adopted",
                adoption_source="manual_exchange_external",
            )
            session._record_closed_trade(
                position=manual_position,
                exit_price=2510.0,
                quantity_closed=1.0,
                exit_time=now + timedelta(minutes=6),
                exit_reason="MANUAL_CLOSE",
            )

            trade_rows = session.log_store.read("closed_trades")
            self.assertEqual(len(trade_rows), 2)
            self.assertEqual(trade_rows[0]["entry_policy_bucket"], "active_policy")
            self.assertTrue(trade_rows[0]["entry_policy_bucket_available"])
            self.assertEqual(trade_rows[0]["entry_policy_lineage"]["structural_key"], "active-lineage")
            self.assertEqual(trade_rows[1]["position_origin"], "adopted")
            self.assertEqual(trade_rows[1]["position_adoption_source"], "manual_exchange_external")
            self.assertEqual(trade_rows[1]["entry_policy_bucket"], "")
            self.assertEqual(trade_rows[1]["entry_policy_lineage"], {})

    def test_live_order_logs_persist_entry_policy_bucket_context(self) -> None:
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
                        "response": {"status": "SUCCESS", "orderId": "live-policy-bucket-1"},
                        "protection_orders": (),
                        "protection_error": "",
                    },
                )()

            def pop_last_preflight_rejection(self):  # type: ignore[no-untyped-def]
                return None

        with tempfile.TemporaryDirectory() as tempdir:
            session = self._build_session()
            run_dir = Path(tempdir) / "output" / "paper-live-shell" / "run-a"
            logs_dir = run_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            session.summary_path = run_dir / "summary.json"
            session.summary_path.with_name("policy_state.json").write_text(
                json.dumps(
                    {
                        "policy_lineage": {
                            "available": True,
                            "structural_key": "active-lineage",
                            "versioned_key": "active-lineage-v1",
                        },
                        "rollout_progression": {"execution_phase": "partial"},
                        "policy_evidence_buckets": {
                            "active_policy": {
                                "available": True,
                                "source": "persisted_policy_validation_evidence",
                                "alignment": {"aligned": True, "status": "aligned", "reason": "POLICY_LINEAGE_MATCH"},
                                "policy_lineage": {
                                    "available": True,
                                    "structural_key": "active-lineage",
                                    "versioned_key": "active-lineage-v1",
                                },
                                "evidence": {"runner_avg_edge_retention_ratio": 0.82},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            session.log_store = JsonlLogStore(logs_dir)
            session.order_tester = None
            session.live_order_executor = AcceptedLiveExecutor()  # type: ignore[assignment]
            now = datetime(2026, 3, 19, 12, 0, tzinfo=timezone.utc)
            state = session.runtime.dispatcher.store.get("BTCUSDT")
            assert state is not None
            state.last_trade_price = 100.0

            session._record_decision(
                decision=make_decision(
                    timestamp=now,
                    symbol="BTCUSDT",
                    predictability_score=91.0,
                    gross_expected_edge_bps=22.0,
                    net_expected_edge_bps=16.0,
                    estimated_round_trip_cost_bps=6.0,
                    order_intent_notional_usd=500.0,
                ),
                state=state,
                timestamp=now,
            )

            live_order_rows = session.log_store.read("live_orders")
            self.assertEqual(len(live_order_rows), 1)
            self.assertEqual(live_order_rows[0]["entry_policy_bucket"], "active_policy")
            self.assertTrue(live_order_rows[0]["entry_policy_bucket_available"])
            self.assertEqual(live_order_rows[0]["entry_policy_bucket_alignment_status"], "aligned")

    def test_futures_reallocation_applies_symbol_reentry_cooldown_to_replaced_symbol(self) -> None:
        settings = self._focus_settings(futures_top_n=1)
        session = self._build_session(settings=settings)
        now = datetime(2026, 3, 8, 12, 10, tzinfo=timezone.utc)
        self._seed_weak_futures_position(session, symbol="ETHUSDT", entry_time=now - timedelta(minutes=15))
        session.capital_report = {
            "futures_available_balance_usd": 50.0,
            "futures_execution_balance_usd": 1.0,
            "can_trade_futures_any": True,
            "futures_requirements": [
                {"symbol": "BTCUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
                {"symbol": "ETHUSDT", "min_notional_usd": 5.0, "min_quantity": 0.001},
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
        self.assertEqual(session.manual_symbol_cooldowns["ETHUSDT"], now + timedelta(minutes=5))

        follow_time = now + timedelta(minutes=1)
        session.runtime.dispatcher.store.put(
            SymbolMarketState(
                symbol="ETHUSDT",
                top_of_book=TopOfBook(199.5, 1.0, 200.5, 1.2, follow_time),
                last_trade_price=200.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=3.0,
                last_update_time=follow_time,
            )
        )
        eth_state = session.runtime.dispatcher.store.get("ETHUSDT")
        assert eth_state is not None

        tested_before = len(session.tested_orders)
        session._execute_recorded_decision(
            managed_decision=make_decision(
                timestamp=follow_time,
                symbol="ETHUSDT",
                predictability_score=95.0,
                gross_expected_edge_bps=38.0,
                net_expected_edge_bps=26.0,
                estimated_round_trip_cost_bps=6.0,
                order_intent_notional_usd=2500.0,
            ),
            state=eth_state,
            timestamp=follow_time,
        )

        self.assertTrue(session._is_manual_symbol_cooldown_active("ETHUSDT", follow_time))
        self.assertEqual(len(session.tested_orders), tested_before)
        self.assertNotIn("ETHUSDT", session.paper_positions)

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
