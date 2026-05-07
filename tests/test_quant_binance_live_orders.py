from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_binance.execution.live_order_adapter import DecisionLiveOrderAdapter
from quant_binance.execution.order_test_adapter import DecisionOrderTestAdapter
from quant_binance.learning import OnlineEdgeLearner
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.service import PaperTradingService
from quant_binance.session import LivePaperSession
from quant_binance.settings import Settings
from quant_binance.observability.log_store import JsonlLogStore


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


class FakeLiveOrderClient:
    def __init__(self) -> None:
        self.calls = 0
        self.leverage_calls: list[tuple[str, int]] = []

    def set_futures_leverage(self, *, symbol, leverage):  # type: ignore[no-untyped-def]
        self.leverage_calls.append((symbol, leverage))
        return {"symbol": symbol, "leverage": leverage}

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        self.calls += 1
        return {"status": "FILLED", "market": market, "orderId": self.calls}


class BitgetMarginCapClient(FakeLiveOrderClient):
    exchange_id = "bitget"

    def __init__(
        self,
        *,
        available_balance_usd: float,
        effective_available_balance_usd: float | None = None,
        union_available_usd: float | None = None,
        leverage_response: dict[str, object] | None = None,
        leverage_error: RuntimeError | None = None,
    ) -> None:
        super().__init__()
        self.available_balance_usd = available_balance_usd
        self.effective_available_balance_usd = effective_available_balance_usd
        self.union_available_usd = union_available_usd
        self.leverage_response = leverage_response if leverage_response is not None else {"leverage": 7}
        self.leverage_error = leverage_error
        self.last_order_params: dict[str, object] | None = None

    def set_futures_leverage(self, *, symbol, leverage):  # type: ignore[no-untyped-def]
        self.leverage_calls.append((symbol, leverage))
        if self.leverage_error is not None:
            raise self.leverage_error
        return dict(self.leverage_response)

    def get_account(self, *, market):  # type: ignore[no-untyped-def]
        if market != "futures":
            return {}
        payload: dict[str, float] = {"availableBalance": self.available_balance_usd}
        if self.effective_available_balance_usd is not None:
            payload["effectiveAvailableBalance"] = self.effective_available_balance_usd
        if self.union_available_usd is not None:
            payload["unionAvailable"] = self.union_available_usd
        return payload

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.last_order_params = dict(order_params)
        return {"status": "FILLED", "market": market, "orderId": self.calls}


class BitgetCrossUnavailableClient(BitgetMarginCapClient):
    def get_account(self, *, market):  # type: ignore[no-untyped-def]
        if market != "futures":
            return {}
        return {
            "availableBalance": self.available_balance_usd,
            "crossedMaxAvailable": 0.0,
            "rawAvailableBalance": self.available_balance_usd,
        }


class BitgetMinOrderGuardClient(BitgetMarginCapClient):
    def _normalize_futures_size(self, *, symbol, size):  # type: ignore[no-untyped-def]
        return 0.0

    def _futures_min_trade_usdt(self, *, symbol):  # type: ignore[no-untyped-def]
        return 5.0

    def get_book_ticker(self, *, market, symbol):  # type: ignore[no-untyped-def]
        return {"bidPrice": "100", "askPrice": "100.5"}


class BitgetBoundaryMinOrderGuardClient(BitgetMarginCapClient):
    def _normalize_futures_size(self, *, symbol, size):  # type: ignore[no-untyped-def]
        return 0.05

    def _futures_min_trade_usdt(self, *, symbol):  # type: ignore[no-untyped-def]
        return 5.0

    def get_book_ticker(self, *, market, symbol):  # type: ignore[no-untyped-def]
        return {"bidPrice": "100", "askPrice": "100.5"}


class BitgetMinNotionalLeverageBoostClient(BitgetMarginCapClient):
    def set_futures_leverage(self, *, symbol, leverage):  # type: ignore[no-untyped-def]
        self.leverage_calls.append((symbol, leverage))
        return {"symbol": symbol, "leverage": leverage}

    def _futures_min_trade_usdt(self, *, symbol):  # type: ignore[no-untyped-def]
        return 5.0

    def _normalize_futures_size(self, *, symbol, size):  # type: ignore[no-untyped-def]
        return round(max(float(size), 0.0), 8)

    def get_book_ticker(self, *, market, symbol):  # type: ignore[no-untyped-def]
        return {"bidPrice": "1.0", "askPrice": "1.01"}


class RaisingLiveOrderClient(FakeLiveOrderClient):
    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise RuntimeError("simulated live order failure")


class CodedRaisingLiveOrderClient(FakeLiveOrderClient):
    def __init__(self, *, code: str, msg: str) -> None:
        super().__init__()
        self.code = code
        self.msg = msg

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise RuntimeError(
            f"Bitget HTTP 400 Bad Request for POST https://api.bitget.com/api/v2/mix/order/place-order: "
            f"code={self.code} msg={self.msg}"
        )


class FirstFailThenFillLiveOrderClient(FakeLiveOrderClient):
    def __init__(self) -> None:
        super().__init__()
        self.order_sizes: list[float] = []

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.order_sizes.append(float(order_params.get("size", order_params.get("quantity", 0.0))))
        if self.calls == 1:
            raise RuntimeError(
                "Bitget HTTP 400 Bad Request for POST https://api.bitget.com/api/v2/mix/order/place-order: "
                "code=40762 msg=The order amount exceeds the balance"
            )
        return {"status": "FILLED", "market": market, "orderId": self.calls}


class SpotCaptureLiveOrderClient(FakeLiveOrderClient):
    def __init__(self) -> None:
        super().__init__()
        self.last_market: str | None = None
        self.last_order_params: dict[str, object] | None = None

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.last_market = str(market)
        self.last_order_params = dict(order_params)
        return {"status": "FILLED", "market": market, "orderId": self.calls}


class MarginRefillThenFillLiveOrderClient(FakeLiveOrderClient):
    exchange_id = "bitget"

    def __init__(self, *, spot_usdt: float = 20.0, eth_qty: float = 0.0) -> None:
        super().__init__()
        self.futures_order_calls = 0
        self.transfers: list[float] = []
        self.spot_usdt = spot_usdt
        self.eth_qty = eth_qty
        self.spot_sell_calls = 0
        self.futures_available = 0.0

    def get_account(self, *, market):  # type: ignore[no-untyped-def]
        if market == "spot":
            balances = [{"asset": "USDT", "free": f"{self.spot_usdt:.8f}", "locked": "0"}]
            if self.eth_qty > 0:
                balances.append({"asset": "ETH", "free": f"{self.eth_qty:.8f}", "locked": "0"})
            return {"balances": balances}
        return {
            "availableBalance": self.futures_available,
            "effectiveAvailableBalance": self.futures_available,
            "crossedMaxAvailable": self.futures_available,
            "rawAvailableBalance": self.futures_available,
        }

    def get_open_orders(self, *, market, symbol=None):  # type: ignore[no-untyped-def]
        return {"orders": []}

    def transfer_spot_to_futures_usdt(self, *, amount_usdt, client_oid=None):  # type: ignore[no-untyped-def]
        amount = float(amount_usdt)
        self.transfers.append(amount)
        self.spot_usdt = max(0.0, self.spot_usdt - amount)
        self.futures_available += amount
        return {"status": "SUCCESS", "amount": amount, "clientOid": client_oid}

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        if market == "spot":
            symbol = str(order_params.get("symbol", "")).upper()
            side = str(order_params.get("side", "")).lower()
            size = float(order_params.get("size", 0.0))
            if symbol == "ETHUSDT" and side == "sell" and size > 0:
                self.spot_sell_calls += 1
                sold = min(size, self.eth_qty)
                self.eth_qty = max(0.0, self.eth_qty - sold)
                self.spot_usdt += sold * 2000.0
            self.calls += 1
            return {"status": "FILLED", "market": market, "orderId": self.calls}
        if market == "futures":
            self.futures_order_calls += 1
            if self.futures_order_calls == 1:
                raise RuntimeError(
                    "Bitget HTTP 400 Bad Request for POST https://api.bitget.com/api/v2/mix/order/place-order: "
                    "code=40762 msg=The order amount exceeds the balance"
                )
            return {"status": "FILLED", "market": market, "orderId": self.futures_order_calls}
        self.calls += 1
        return {"status": "FILLED", "market": market, "orderId": self.calls}

    def get_book_ticker(self, *, market, symbol):  # type: ignore[no-untyped-def]
        if market == "spot" and str(symbol).upper() == "ETHUSDT":
            return {"bidPrice": "2000", "askPrice": "2001"}
        if market == "futures":
            if str(symbol).upper() == "ETHUSDT":
                return {"bidPrice": "2000", "askPrice": "2001"}
            return {"bidPrice": "85000", "askPrice": "85001"}
        raise RuntimeError("unsupported symbol")


class MarginReleaseThenFillLiveOrderClient(FakeLiveOrderClient):
    exchange_id = "bitget"

    def __init__(self) -> None:
        super().__init__()
        self.release_calls = 0
        self.release_sides: list[str] = []
        self.futures_order_calls = 0
        self.released = False
        self.futures_available = 0.0

    def set_futures_leverage(self, *, symbol, leverage):  # type: ignore[no-untyped-def]
        self.leverage_calls.append((symbol, leverage))
        return {"symbol": symbol, "leverage": leverage}

    def get_account(self, *, market):  # type: ignore[no-untyped-def]
        if market == "spot":
            return {"balances": [{"asset": "USDT", "free": "0.0", "locked": "0"}]}
        return {
            "availableBalance": 80.0,
            "effectiveAvailableBalance": self.futures_available,
            "crossedMaxAvailable": self.futures_available,
            "rawAvailableBalance": 80.0,
            "unionAvailable": 15.0,
        }

    def get_open_orders(self, *, market, symbol=None):  # type: ignore[no-untyped-def]
        return {"orders": []}

    def get_futures_positions(self):  # type: ignore[no-untyped-def]
        return [
            {
                "symbol": "ETHUSDT",
                "holdSide": "long",
                "total": 0.5,
                "available": 0.5,
                "marginSize": 25.0,
            }
        ]

    def _futures_min_trade_usdt(self, *, symbol):  # type: ignore[no-untyped-def]
        return 5.0

    def get_book_ticker(self, *, market, symbol):  # type: ignore[no-untyped-def]
        if market == "futures" and str(symbol).upper() == "ETHUSDT":
            return {"bidPrice": "2000", "askPrice": "2001"}
        if market == "futures":
            return {"bidPrice": "85000", "askPrice": "85001"}
        return {"bidPrice": "1", "askPrice": "1.1"}

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        if market != "futures":
            self.calls += 1
            return {"status": "FILLED", "market": market, "orderId": self.calls}
        symbol = str(order_params.get("symbol", "")).upper()
        self.futures_order_calls += 1
        if symbol == "ETHUSDT":
            self.release_calls += 1
            self.release_sides.append(str(order_params.get("side", "")).lower())
            self.released = True
            self.futures_available = 1.0
            return {"status": "FILLED", "market": market, "orderId": f"release-{self.release_calls}"}
        if symbol == "BTCUSDT" and not self.released:
            raise RuntimeError(
                "Bitget HTTP 400 Bad Request for POST https://api.bitget.com/api/v2/mix/order/place-order: "
                "code=40762 msg=The order amount exceeds the balance"
            )
        self.calls += 1
        return {"status": "FILLED", "market": market, "orderId": self.calls}


class RaisingTestOrderClient:
    def test_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        raise RuntimeError("simulated test order failure")


class SymbolSupportRestClient:
    def __init__(self) -> None:
        self.spot_symbols = {"BTCUSDT", "ETHUSDT", "AAPLUSDT"}
        self.futures_symbols = {"BTCUSDT", "ETHUSDT"}

    def get_exchange_info(self, *, market):  # type: ignore[no-untyped-def]
        symbols = self.spot_symbols if market == "spot" else self.futures_symbols
        return {"symbols": [{"symbol": symbol} for symbol in sorted(symbols)]}

    def get_account(self, *, market):  # type: ignore[no-untyped-def]
        if market == "spot":
            return {"balances": [{"asset": "USDT", "free": "1000.0", "locked": "0"}]}
        return {"availableBalance": 1000.0, "effectiveAvailableBalance": 1000.0}

    def get_open_orders(self, *, market, symbol=None):  # type: ignore[no-untyped-def]
        return {"orders": []}


class QuantBinanceLiveOrdersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def _load_settings_for_profile(self, profile: str) -> Settings:
        previous = os.environ.get("STRATEGY_PROFILE")
        os.environ["STRATEGY_PROFILE"] = profile
        try:
            return Settings.load(CONFIG_PATH)
        finally:
            if previous is None:
                os.environ.pop("STRATEGY_PROFILE", None)
            else:
                os.environ["STRATEGY_PROFILE"] = previous

    def test_live_order_adapter_executes_market_order(self) -> None:
        from quant_binance.models import DecisionIntent

        decision = DecisionIntent(
            decision_id="d1",
            decision_hash="hash-1",
            snapshot_id="s1",
            config_version="2026-03-08.v1",
            timestamp=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.8,
            volume_confirmation=0.7,
            liquidity_score=0.8,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=82.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=2000.0,
            stop_distance_bps=45.0,
        )
        live_client = FakeLiveOrderClient()
        adapter = DecisionLiveOrderAdapter(live_client, self.settings)  # type: ignore[arg-type]
        result = adapter.execute_decision(decision=decision, reference_price=50000.0)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.accepted)
        self.assertEqual(result.market, "futures")
        self.assertEqual(live_client.leverage_calls, [("BTCUSDT", 2)])

    def test_live_order_adapter_uses_active_profile_max_leverage_for_strong_futures_short(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("active")
        decision = DecisionIntent(
            decision_id="d-strong-short",
            decision_hash="hash-strong-short",
            snapshot_id="s-strong-short",
            config_version="2026-03-10.v1",
            timestamp=datetime(2026, 3, 11, 0, 30, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="short",
            trend_direction=-1,
            trend_strength=0.86,
            volume_confirmation=0.8,
            liquidity_score=0.84,
            volatility_penalty=0.24,
            overheat_penalty=0.16,
            predictability_score=87.0,
            gross_expected_edge_bps=40.0,
            net_expected_edge_bps=28.0,
            estimated_round_trip_cost_bps=12.0,
            order_intent_notional_usd=140.0,
            stop_distance_bps=45.0,
        )
        live_client = FakeLiveOrderClient()
        adapter = DecisionLiveOrderAdapter(live_client, settings)  # type: ignore[arg-type]

        result = adapter.execute_decision(decision=decision, reference_price=50000.0)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.market, "futures")
        self.assertEqual(result.side, "SELL")
        self.assertEqual(live_client.leverage_calls, [("BTCUSDT", 10)])

    def test_live_order_adapter_uses_soft_active_leverage_for_borderline_futures_setup(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("active")
        decision = DecisionIntent(
            decision_id="d-soft-short",
            decision_hash="hash-soft-short",
            snapshot_id="s-soft-short",
            config_version="2026-03-10.v1",
            timestamp=datetime(2026, 3, 11, 0, 35, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="short",
            trend_direction=-1,
            trend_strength=0.64,
            volume_confirmation=0.61,
            liquidity_score=0.66,
            volatility_penalty=0.66,
            overheat_penalty=0.3,
            predictability_score=67.0,
            gross_expected_edge_bps=33.0,
            net_expected_edge_bps=12.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=60.0,
            stop_distance_bps=55.0,
        )
        live_client = FakeLiveOrderClient()
        adapter = DecisionLiveOrderAdapter(live_client, settings)  # type: ignore[arg-type]

        adapter.execute_decision(decision=decision, reference_price=50000.0)

        self.assertEqual(live_client.leverage_calls, [("BTCUSDT", 4)])

    def test_live_order_adapter_reuses_recent_symbol_leverage_setting(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("active")
        decision = DecisionIntent(
            decision_id="d-cache-1",
            decision_hash="hash-cache-1",
            snapshot_id="s-cache-1",
            config_version="2026-03-12.v1",
            timestamp=datetime(2026, 3, 12, 0, 35, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="short",
            trend_direction=-1,
            trend_strength=0.64,
            volume_confirmation=0.61,
            liquidity_score=0.66,
            volatility_penalty=0.66,
            overheat_penalty=0.3,
            predictability_score=67.0,
            gross_expected_edge_bps=33.0,
            net_expected_edge_bps=12.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=60.0,
            stop_distance_bps=55.0,
        )
        live_client = FakeLiveOrderClient()
        adapter = DecisionLiveOrderAdapter(live_client, settings)  # type: ignore[arg-type]

        adapter.execute_decision(decision=decision, reference_price=50000.0)
        adapter.execute_decision(decision=decision, reference_price=50010.0)

        self.assertEqual(live_client.leverage_calls, [("BTCUSDT", 4)])
        self.assertEqual(live_client.calls, 2)

    def test_live_order_adapter_uses_quote_order_qty_for_spot_market_buy(self) -> None:
        from quant_binance.models import DecisionIntent

        decision = DecisionIntent(
            decision_id="d2",
            decision_hash="hash-2",
            snapshot_id="s2",
            config_version="2026-03-10.v1",
            timestamp=datetime(2026, 3, 10, 0, 30, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="spot",
            side="long",
            trend_direction=1,
            trend_strength=0.8,
            volume_confirmation=0.7,
            liquidity_score=0.8,
            volatility_penalty=0.2,
            overheat_penalty=0.1,
            predictability_score=66.0,
            gross_expected_edge_bps=30.0,
            net_expected_edge_bps=18.0,
            estimated_round_trip_cost_bps=12.0,
            order_intent_notional_usd=2400.0,
            stop_distance_bps=80.0,
        )
        adapter = DecisionLiveOrderAdapter(FakeLiveOrderClient(), self.settings)  # type: ignore[arg-type]
        built = adapter.build_order_params(decision=decision, reference_price=50000.0)
        assert built is not None
        market, params = built
        self.assertEqual(market, "spot")
        self.assertEqual(params["side"], "BUY")
        self.assertEqual(params["quoteOrderQty"], "2400.00")
        self.assertNotIn("quantity", params)

    def test_live_order_adapter_caps_bitget_futures_size_by_available_balance(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("alpha_max")
        decision = DecisionIntent(
            decision_id="d-bitget-cap",
            decision_hash="hash-bitget-cap",
            snapshot_id="s-bitget-cap",
            config_version="2026-03-11.v1",
            timestamp=datetime(2026, 3, 11, 8, 0, tzinfo=timezone.utc),
            symbol="XRPUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.58,
            volume_confirmation=0.57,
            liquidity_score=0.62,
            volatility_penalty=0.72,
            overheat_penalty=0.5,
            predictability_score=59.7,
            gross_expected_edge_bps=11.4,
            net_expected_edge_bps=1.2,
            estimated_round_trip_cost_bps=10.1,
            order_intent_notional_usd=1245.607477,
            stop_distance_bps=134.8,
        )
        client = BitgetMarginCapClient(
            available_balance_usd=40.0,
            leverage_response={"leverage": 7},
        )
        adapter = DecisionLiveOrderAdapter(client, settings)  # type: ignore[arg-type]

        result = adapter.execute_decision(decision=decision, reference_price=8.185)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsNotNone(client.last_order_params)
        assert client.last_order_params is not None
        capped_size = float(client.last_order_params["size"])
        uncapped_size = decision.order_intent_notional_usd / 8.185
        self.assertLess(capped_size, uncapped_size)
        expected_max_notional = 40.0 * 6.0 * 0.9
        self.assertLessEqual(capped_size * 8.185, expected_max_notional + 1e-6)

    def test_live_order_adapter_handles_bitget_leverage_margin_error_with_cached_or_target_fallback(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("alpha_max")
        decision = DecisionIntent(
            decision_id="d-bitget-lev-fail",
            decision_hash="hash-bitget-lev-fail",
            snapshot_id="s-bitget-lev-fail",
            config_version="2026-03-11.v1",
            timestamp=datetime(2026, 3, 11, 8, 15, tzinfo=timezone.utc),
            symbol="XRPUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.63,
            volume_confirmation=0.6,
            liquidity_score=0.64,
            volatility_penalty=0.7,
            overheat_penalty=0.45,
            predictability_score=62.6,
            gross_expected_edge_bps=12.0,
            net_expected_edge_bps=2.0,
            estimated_round_trip_cost_bps=10.2,
            order_intent_notional_usd=582.0,
            stop_distance_bps=128.0,
        )
        client = BitgetMarginCapClient(
            available_balance_usd=40.0,
            leverage_error=RuntimeError(
                "Bitget HTTP 400 Bad Request for POST https://api.bitget.com/api/v2/mix/account/set-leverage: "
                "code=40893 msg=Unable to update the leverage factor of this position, there is not enough margin!"
            ),
        )
        adapter = DecisionLiveOrderAdapter(client, settings)  # type: ignore[arg-type]

        result = adapter.execute_decision(decision=decision, reference_price=8.185)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(client.leverage_calls, [("XRPUSDT", 6)])
        assert client.last_order_params is not None
        capped_size = float(client.last_order_params["size"])
        expected_max_notional = 40.0 * 6.0 * 0.9
        self.assertLessEqual(capped_size * 8.185, expected_max_notional + 1e-6)

    def test_live_order_adapter_prefers_effective_available_balance_for_bitget_futures_cap(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("alpha_max")
        decision = DecisionIntent(
            decision_id="d-bitget-effective-cap",
            decision_hash="hash-bitget-effective-cap",
            snapshot_id="s-bitget-effective-cap",
            config_version="2026-03-12.v1",
            timestamp=datetime(2026, 3, 12, 1, 0, tzinfo=timezone.utc),
            symbol="ETHUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.66,
            volume_confirmation=0.63,
            liquidity_score=0.67,
            volatility_penalty=0.54,
            overheat_penalty=0.25,
            predictability_score=69.2,
            gross_expected_edge_bps=20.0,
            net_expected_edge_bps=8.0,
            estimated_round_trip_cost_bps=9.5,
            order_intent_notional_usd=900.0,
            stop_distance_bps=120.0,
        )
        client = BitgetMarginCapClient(
            available_balance_usd=40.0,
            effective_available_balance_usd=18.0,
            leverage_response={"leverage": 6},
        )
        adapter = DecisionLiveOrderAdapter(client, settings)  # type: ignore[arg-type]

        result = adapter.execute_decision(decision=decision, reference_price=3000.0)

        self.assertIsNotNone(result)
        assert result is not None
        assert client.last_order_params is not None
        capped_size = float(client.last_order_params["size"])
        capped_notional = capped_size * 3000.0
        expected_max_notional = 18.0 * 6.0 * 0.9
        self.assertLessEqual(capped_notional, expected_max_notional + 1e-6)

    def test_live_order_adapter_falls_back_when_cross_available_is_zero(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("alpha_max")
        decision = DecisionIntent(
            decision_id="d-bitget-cross-zero",
            decision_hash="hash-bitget-cross-zero",
            snapshot_id="s-bitget-cross-zero",
            config_version="2026-03-12.v1",
            timestamp=datetime(2026, 3, 12, 1, 10, tzinfo=timezone.utc),
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.67,
            volume_confirmation=0.65,
            liquidity_score=0.68,
            volatility_penalty=0.52,
            overheat_penalty=0.24,
            predictability_score=70.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=10.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=1200.0,
            stop_distance_bps=100.0,
        )
        client = BitgetCrossUnavailableClient(available_balance_usd=40.0, leverage_response={"leverage": 6})
        adapter = DecisionLiveOrderAdapter(client, settings)  # type: ignore[arg-type]

        result = adapter.execute_decision(decision=decision, reference_price=85000.0)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(client.calls, 1)
        assert client.last_order_params is not None
        fallback_available = 40.0 * 0.08
        expected_max_notional = fallback_available * 6.0 * 0.9
        capped_size = float(client.last_order_params["size"])
        self.assertLessEqual(capped_size * 85000.0, expected_max_notional + 1e-6)

    def test_live_order_adapter_skips_bitget_futures_order_below_symbol_minimum(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("alpha_max")
        decision = DecisionIntent(
            decision_id="d-bitget-min-order-guard",
            decision_hash="hash-bitget-min-order-guard",
            snapshot_id="s-bitget-min-order-guard",
            config_version="2026-03-12.v1",
            timestamp=datetime(2026, 3, 12, 1, 15, tzinfo=timezone.utc),
            symbol="ETHUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.67,
            volume_confirmation=0.65,
            liquidity_score=0.68,
            volatility_penalty=0.52,
            overheat_penalty=0.24,
            predictability_score=70.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=10.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=1200.0,
            stop_distance_bps=100.0,
        )
        client = BitgetMinOrderGuardClient(available_balance_usd=10.0, leverage_response={"leverage": 6})
        adapter = DecisionLiveOrderAdapter(client, settings)  # type: ignore[arg-type]

        result = adapter.execute_decision(decision=decision, reference_price=3000.0)

        self.assertIsNone(result)
        self.assertEqual(client.calls, 0)

    def test_live_order_adapter_skips_bitget_futures_order_at_exact_minimum_boundary(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("alpha_max")
        decision = DecisionIntent(
            decision_id="d-bitget-min-order-boundary",
            decision_hash="hash-bitget-min-order-boundary",
            snapshot_id="s-bitget-min-order-boundary",
            config_version="2026-03-12.v1",
            timestamp=datetime(2026, 3, 12, 1, 17, tzinfo=timezone.utc),
            symbol="ETHUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.67,
            volume_confirmation=0.65,
            liquidity_score=0.68,
            volatility_penalty=0.52,
            overheat_penalty=0.24,
            predictability_score=70.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=10.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=1200.0,
            stop_distance_bps=100.0,
        )
        client = BitgetBoundaryMinOrderGuardClient(available_balance_usd=10.0, leverage_response={"leverage": 6})
        adapter = DecisionLiveOrderAdapter(client, settings)  # type: ignore[arg-type]

        result = adapter.execute_decision(decision=decision, reference_price=3000.0)

        self.assertIsNone(result)
        self.assertEqual(client.calls, 0)

    def test_live_order_adapter_boosts_leverage_to_meet_bitget_min_notional_when_openable_is_low(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("profit_push")
        decision = DecisionIntent(
            decision_id="d-bitget-min-notional-boost",
            decision_hash="hash-bitget-min-notional-boost",
            snapshot_id="s-bitget-min-notional-boost",
            config_version="2026-03-12.v1",
            timestamp=datetime(2026, 3, 12, 1, 25, tzinfo=timezone.utc),
            symbol="WLDUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="short",
            trend_direction=-1,
            trend_strength=0.62,
            volume_confirmation=0.55,
            liquidity_score=0.6,
            volatility_penalty=0.62,
            overheat_penalty=0.35,
            predictability_score=60.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=6.0,
            estimated_round_trip_cost_bps=10.0,
            order_intent_notional_usd=1200.0,
            stop_distance_bps=100.0,
        )
        client = BitgetMinNotionalLeverageBoostClient(
            available_balance_usd=40.0,
            effective_available_balance_usd=0.52,
            leverage_response={"leverage": 7},
        )
        adapter = DecisionLiveOrderAdapter(client, settings)  # type: ignore[arg-type]

        result = adapter.execute_decision(decision=decision, reference_price=1.0)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreaterEqual(len(client.leverage_calls), 2)
        self.assertEqual(client.leverage_calls[0][1], 7)
        self.assertGreaterEqual(client.leverage_calls[-1][1], 11)
        assert client.last_order_params is not None
        self.assertGreaterEqual(float(client.last_order_params["size"]), 5.0)

    def test_session_survives_live_order_exception(self) -> None:
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
        live_client = RaisingLiveOrderClient()
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            live_order_executor=DecisionLiveOrderAdapter(live_client),  # type: ignore[arg-type]
            order_tester=DecisionOrderTestAdapter(RaisingTestOrderClient()),  # type: ignore[arg-type]
            log_store=JsonlLogStore(ROOT / ".tmp-test-logs"),
        )
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
        self.assertEqual(len(session.decisions), 1)
        self.assertEqual(len(session.live_orders), 0)
        self.assertEqual(len(session.tested_orders), 0)

    def test_session_prevents_duplicate_live_order_hash(self) -> None:
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
        live_client = FakeLiveOrderClient()
        learner = OnlineEdgeLearner(min_observations=1)
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            live_order_executor=DecisionLiveOrderAdapter(live_client),  # type: ignore[arg-type]
            learner=learner,
        )
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
        session.process_payload(payload, now=now)
        session.process_payload(payload, now=now)
        self.assertEqual(live_client.calls, 1)

    def test_session_applies_error_code_cooldown_to_avoid_live_order_spam(self) -> None:
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
        live_client = CodedRaisingLiveOrderClient(code="40762", msg="The order amount exceeds the balance")
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            live_order_executor=DecisionLiveOrderAdapter(live_client),  # type: ignore[arg-type]
        )
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
        second_payload = {
            "stream": "btcusdt@kline_5m",
            "data": {
                "s": "BTCUSDT",
                "k": {
                    "i": "5m",
                    "t": 1772971500000,
                    "T": 1772971800000,
                    "o": "50020",
                    "h": "50150",
                    "l": "49990",
                    "c": "50110",
                    "v": "13",
                    "q": "640000",
                    "x": True,
                },
            },
        }
        session.process_payload(payload, now=now)
        session.process_payload(second_payload, now=now + timedelta(seconds=60))
        self.assertEqual(live_client.calls, 1)
        self.assertIn("BTCUSDT", session.live_error_cooldown_until_by_symbol)

    def test_session_marks_failing_fingerprint_to_block_identical_retries(self) -> None:
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
        live_client = CodedRaisingLiveOrderClient(code="40762", msg="The order amount exceeds the balance")
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            live_order_executor=DecisionLiveOrderAdapter(live_client),  # type: ignore[arg-type]
        )
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
        session.process_payload(payload, now=now)
        session.process_payload(payload, now=now + timedelta(seconds=360))
        self.assertEqual(live_client.calls, 1)

    def test_session_reduces_futures_notional_scale_after_balance_error(self) -> None:
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
        live_client = FirstFailThenFillLiveOrderClient()
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            live_order_executor=DecisionLiveOrderAdapter(live_client),  # type: ignore[arg-type]
        )
        session.capital_report = {
            "spot_available_balance_usd": 0.0,
            "futures_available_balance_usd": 100.0,
            "can_trade_spot_any": False,
            "can_trade_futures_any": True,
            "spot_requirements": [],
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0}],
        }
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
        payload_after_cooldown = {
            "stream": "btcusdt@kline_5m",
            "data": {
                "s": "BTCUSDT",
                "k": {
                    "i": "5m",
                    "t": 1772971500000,
                    "T": 1772971800000,
                    "o": "50020",
                    "h": "50150",
                    "l": "49990",
                    "c": "50110",
                    "v": "13",
                    "q": "640000",
                    "x": True,
                },
            },
        }
        session.process_payload(payload, now=now)
        session.process_payload(payload_after_cooldown, now=now + timedelta(seconds=301))
        self.assertEqual(live_client.calls, 2)
        self.assertLess(live_client.order_sizes[1], live_client.order_sizes[0])
        self.assertIn("BTCUSDT", session.futures_notional_scale_by_symbol)
        self.assertLess(session.futures_notional_scale_by_symbol["BTCUSDT"], 1.0)

    def test_session_skips_live_order_when_edge_is_too_thin_for_live_execution(self) -> None:
        from quant_binance.models import DecisionIntent

        now = datetime(2026, 3, 12, 1, 20, tzinfo=timezone.utc)
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
        live_client = SpotCaptureLiveOrderClient()
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            live_order_executor=DecisionLiveOrderAdapter(live_client, self.settings),  # type: ignore[arg-type]
        )
        decision = DecisionIntent(
            decision_id="thin-live-edge-test",
            decision_hash="thin-live-edge-hash",
            snapshot_id="thin-live-edge-snapshot",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.7,
            volume_confirmation=0.69,
            liquidity_score=0.74,
            volatility_penalty=0.5,
            overheat_penalty=0.24,
            predictability_score=66.0,
            gross_expected_edge_bps=8.5,
            net_expected_edge_bps=0.5,
            estimated_round_trip_cost_bps=8.0,
            order_intent_notional_usd=600.0,
            stop_distance_bps=95.0,
        )

        session._record_decision(decision=decision, state=store.get("BTCUSDT"), timestamp=now)

        self.assertEqual(live_client.calls, 0)
        self.assertIn("BTCUSDT", session.last_executed_fingerprint_by_symbol)

    def test_session_applies_global_cooldown_after_min_order_error(self) -> None:
        from quant_binance.models import DecisionIntent

        now = datetime(2026, 3, 12, 1, 25, tzinfo=timezone.utc)
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
        store.put(
            SymbolMarketState(
                symbol="ETHUSDT",
                top_of_book=TopOfBook(2999.5, 3.0, 3000.5, 2.8, now),
                last_trade_price=3000.0,
                funding_rate=0.0001,
                open_interest=900000.0,
                basis_bps=2.0,
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
        live_client = CodedRaisingLiveOrderClient(code="45110", msg="less than the minimum amount 5 USDT")
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            live_order_executor=DecisionLiveOrderAdapter(live_client, self.settings),  # type: ignore[arg-type]
        )
        first = DecisionIntent(
            decision_id="global-cooldown-1",
            decision_hash="global-cooldown-hash-1",
            snapshot_id="global-cooldown-snapshot-1",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.74,
            volume_confirmation=0.7,
            liquidity_score=0.79,
            volatility_penalty=0.48,
            overheat_penalty=0.2,
            predictability_score=71.0,
            gross_expected_edge_bps=15.0,
            net_expected_edge_bps=6.0,
            estimated_round_trip_cost_bps=8.0,
            order_intent_notional_usd=700.0,
            stop_distance_bps=90.0,
        )
        second = DecisionIntent(
            decision_id="global-cooldown-2",
            decision_hash="global-cooldown-hash-2",
            snapshot_id="global-cooldown-snapshot-2",
            config_version="2026-03-12.v1",
            timestamp=now + timedelta(seconds=30),
            symbol="ETHUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.72,
            volume_confirmation=0.69,
            liquidity_score=0.78,
            volatility_penalty=0.49,
            overheat_penalty=0.22,
            predictability_score=70.0,
            gross_expected_edge_bps=14.0,
            net_expected_edge_bps=5.8,
            estimated_round_trip_cost_bps=8.2,
            order_intent_notional_usd=680.0,
            stop_distance_bps=92.0,
        )

        session._record_decision(decision=first, state=store.get("BTCUSDT"), timestamp=now)
        session._record_decision(decision=second, state=store.get("ETHUSDT"), timestamp=now + timedelta(seconds=30))

        self.assertEqual(live_client.calls, 1)
        self.assertEqual(session.live_error_global_code, "45110")
        assert session.live_error_global_cooldown_until is not None
        self.assertGreater(session.live_error_global_cooldown_until, now)

    def test_session_liquidates_spot_inventory_when_cash_signal_is_bearish(self) -> None:
        from quant_binance.models import DecisionIntent

        now = datetime(2026, 3, 12, 2, 0, tzinfo=timezone.utc)
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
        live_client = SpotCaptureLiveOrderClient()
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            live_order_executor=DecisionLiveOrderAdapter(live_client, self.settings),  # type: ignore[arg-type]
        )
        session.account_snapshot = {
            "spot": {"balances": [{"asset": "BTC", "free": "0.01000000", "locked": "0"}]},
            "futures": {},
        }
        session.capital_report = {
            "spot_available_balance_usd": 0.0,
            "futures_available_balance_usd": 0.0,
            "can_trade_spot_any": False,
            "can_trade_futures_any": False,
            "spot_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0}],
            "futures_requirements": [],
        }
        decision = DecisionIntent(
            decision_id="spot-liquidation-test",
            decision_hash="spot-liquidation-hash",
            snapshot_id="spot-liquidation-snapshot",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="cash",
            final_mode="cash",
            side="flat",
            trend_direction=-1,
            trend_strength=0.42,
            volume_confirmation=0.41,
            liquidity_score=0.62,
            volatility_penalty=0.58,
            overheat_penalty=0.3,
            predictability_score=44.0,
            gross_expected_edge_bps=0.0,
            net_expected_edge_bps=-10.0,
            estimated_round_trip_cost_bps=20.0,
            order_intent_notional_usd=0.0,
            stop_distance_bps=0.0,
            rejection_reasons=("SCORE_TOO_LOW",),
        )

        session._record_decision(decision=decision, state=store.get("BTCUSDT"), timestamp=now)

        self.assertEqual(live_client.calls, 1)
        self.assertEqual(live_client.last_market, "spot")
        assert live_client.last_order_params is not None
        self.assertEqual(live_client.last_order_params["side"], "SELL")
        self.assertGreater(float(live_client.last_order_params["quantity"]), 0.0)

    def test_session_refills_futures_margin_on_40762_then_retries_once(self) -> None:
        from quant_binance.models import DecisionIntent

        now = datetime(2026, 3, 12, 2, 30, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(84999.5, 1.0, 85000.5, 1.2, now),
                last_trade_price=85000.0,
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
        live_client = MarginRefillThenFillLiveOrderClient()
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=live_client,  # type: ignore[arg-type]
            live_order_executor=DecisionLiveOrderAdapter(live_client, self.settings),  # type: ignore[arg-type]
        )
        session.account_snapshot = {
            "spot": {"balances": [{"asset": "USDT", "free": "20.00", "locked": "0"}]},
            "futures": {"availableBalance": 0.0, "effectiveAvailableBalance": 0.0, "crossedMaxAvailable": 0.0},
        }
        session.capital_report = {
            "spot_available_balance_usd": 20.0,
            "futures_available_balance_usd": 100.0,
            "can_trade_spot_any": True,
            "can_trade_futures_any": True,
            "spot_requirements": [],
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0}],
        }
        decision = DecisionIntent(
            decision_id="futures-refill-test",
            decision_hash="futures-refill-hash",
            snapshot_id="futures-refill-snapshot",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.75,
            volume_confirmation=0.72,
            liquidity_score=0.8,
            volatility_penalty=0.52,
            overheat_penalty=0.2,
            predictability_score=72.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=12.0,
            estimated_round_trip_cost_bps=8.0,
            order_intent_notional_usd=1200.0,
            stop_distance_bps=100.0,
        )

        session._record_decision(decision=decision, state=store.get("BTCUSDT"), timestamp=now)

        self.assertGreaterEqual(live_client.futures_order_calls, 2)
        self.assertGreaterEqual(len(live_client.transfers), 1)
        self.assertEqual(len(session.live_orders), 1)

    def test_session_refills_margin_by_selling_spot_asset_then_retries(self) -> None:
        from quant_binance.models import DecisionIntent

        now = datetime(2026, 3, 12, 2, 35, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(84999.5, 1.0, 85000.5, 1.2, now),
                last_trade_price=85000.0,
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
        live_client = MarginRefillThenFillLiveOrderClient(spot_usdt=0.0, eth_qty=0.02)
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=live_client,  # type: ignore[arg-type]
            live_order_executor=DecisionLiveOrderAdapter(live_client, self.settings),  # type: ignore[arg-type]
        )
        session.account_snapshot = {
            "spot": {"balances": [{"asset": "USDT", "free": "0.00", "locked": "0"}, {"asset": "ETH", "free": "0.02000000", "locked": "0"}]},
            "futures": {"availableBalance": 0.0, "effectiveAvailableBalance": 0.0, "crossedMaxAvailable": 0.0},
        }
        session.capital_report = {
            "spot_available_balance_usd": 0.0,
            "futures_available_balance_usd": 100.0,
            "can_trade_spot_any": True,
            "can_trade_futures_any": True,
            "spot_requirements": [],
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0}],
        }
        decision = DecisionIntent(
            decision_id="futures-refill-spot-sale-test",
            decision_hash="futures-refill-spot-sale-hash",
            snapshot_id="futures-refill-spot-sale-snapshot",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.75,
            volume_confirmation=0.72,
            liquidity_score=0.8,
            volatility_penalty=0.52,
            overheat_penalty=0.2,
            predictability_score=72.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=12.0,
            estimated_round_trip_cost_bps=8.0,
            order_intent_notional_usd=1200.0,
            stop_distance_bps=100.0,
        )

        session._record_decision(decision=decision, state=store.get("BTCUSDT"), timestamp=now)

        self.assertGreaterEqual(live_client.spot_sell_calls, 1)
        self.assertGreaterEqual(len(live_client.transfers), 1)
        self.assertGreaterEqual(live_client.futures_order_calls, 2)
        self.assertEqual(len(session.live_orders), 1)

    def test_session_skips_dust_spot_assets_during_margin_refill(self) -> None:
        from quant_binance.models import DecisionIntent

        now = datetime(2026, 3, 12, 2, 40, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(84999.5, 1.0, 85000.5, 1.2, now),
                last_trade_price=85000.0,
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
        # 0.000008 ETH * 2000 ~= 0.016 USDT: always below spot min trade amount.
        live_client = MarginRefillThenFillLiveOrderClient(spot_usdt=0.0, eth_qty=0.000008)
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=live_client,  # type: ignore[arg-type]
            live_order_executor=DecisionLiveOrderAdapter(live_client, self.settings),  # type: ignore[arg-type]
        )
        session.account_snapshot = {
            "spot": {"balances": [{"asset": "USDT", "free": "0.00", "locked": "0"}, {"asset": "ETH", "free": "0.00000800", "locked": "0"}]},
            "futures": {"availableBalance": 0.0, "effectiveAvailableBalance": 0.0, "crossedMaxAvailable": 0.0},
        }
        session.capital_report = {
            "spot_available_balance_usd": 0.0,
            "futures_available_balance_usd": 100.0,
            "can_trade_spot_any": True,
            "can_trade_futures_any": True,
            "spot_requirements": [],
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0}],
        }
        decision = DecisionIntent(
            decision_id="futures-refill-dust-skip-test",
            decision_hash="futures-refill-dust-skip-hash",
            snapshot_id="futures-refill-dust-skip-snapshot",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.75,
            volume_confirmation=0.72,
            liquidity_score=0.8,
            volatility_penalty=0.52,
            overheat_penalty=0.2,
            predictability_score=72.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=12.0,
            estimated_round_trip_cost_bps=8.0,
            order_intent_notional_usd=1200.0,
            stop_distance_bps=100.0,
        )

        session._record_decision(decision=decision, state=store.get("BTCUSDT"), timestamp=now)

        self.assertEqual(live_client.spot_sell_calls, 0)
        self.assertEqual(len(live_client.transfers), 0)
        self.assertGreaterEqual(live_client.futures_order_calls, 1)
        self.assertEqual(len(session.live_orders), 0)

    def test_session_routes_futures_long_to_spot_for_spot_only_symbol(self) -> None:
        from quant_binance.models import DecisionIntent

        now = datetime(2026, 3, 12, 3, 0, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="AAPLUSDT",
                top_of_book=TopOfBook(180.0, 200.0, 180.1, 180.0, now),
                last_trade_price=180.05,
                funding_rate=0.0,
                open_interest=0.0,
                basis_bps=0.0,
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
        live_client = SpotCaptureLiveOrderClient()
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=SymbolSupportRestClient(),  # type: ignore[arg-type]
            live_order_executor=DecisionLiveOrderAdapter(live_client, self.settings),  # type: ignore[arg-type]
        )
        decision = DecisionIntent(
            decision_id="spot-only-symbol-route-test",
            decision_hash="spot-only-symbol-route-hash",
            snapshot_id="spot-only-symbol-route-snapshot",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="AAPLUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.76,
            volume_confirmation=0.72,
            liquidity_score=0.8,
            volatility_penalty=0.34,
            overheat_penalty=0.1,
            predictability_score=74.0,
            gross_expected_edge_bps=26.0,
            net_expected_edge_bps=14.0,
            estimated_round_trip_cost_bps=8.0,
            order_intent_notional_usd=800.0,
            stop_distance_bps=70.0,
        )

        session._record_decision(decision=decision, state=store.get("AAPLUSDT"), timestamp=now)

        self.assertEqual(live_client.calls, 1)
        self.assertEqual(live_client.last_market, "spot")
        assert live_client.last_order_params is not None
        self.assertEqual(str(live_client.last_order_params.get("side", "")).upper(), "BUY")

    def test_session_releases_existing_futures_position_when_openable_margin_is_zero(self) -> None:
        from quant_binance.models import DecisionIntent

        settings = self._load_settings_for_profile("profit_push")
        now = datetime(2026, 3, 12, 3, 10, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol="BTCUSDT",
                top_of_book=TopOfBook(84999.5, 1.0, 85000.5, 1.2, now),
                last_trade_price=85000.0,
                funding_rate=0.0001,
                open_interest=1000000.0,
                basis_bps=3.0,
                last_update_time=now,
            )
        )
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(store),
            paper_service=PaperTradingService(settings, router=ExecutionRouter()),
            primitive_builder=lambda symbol, decision_time: make_primitive(),
            history_provider=lambda symbol, decision_time: make_history(),
            decision_interval_minutes=settings.decision_engine.decision_interval_minutes,
        )
        live_client = MarginReleaseThenFillLiveOrderClient()
        session = LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=live_client,  # type: ignore[arg-type]
            live_order_executor=DecisionLiveOrderAdapter(live_client, settings),  # type: ignore[arg-type]
        )
        session.account_snapshot = {
            "spot": {"balances": [{"asset": "USDT", "free": "0.00", "locked": "0"}]},
            "futures": {"availableBalance": 80.0, "effectiveAvailableBalance": 0.0, "crossedMaxAvailable": 0.0},
        }
        session.capital_report = {
            "spot_available_balance_usd": 0.0,
            "futures_available_balance_usd": 80.0,
            "can_trade_spot_any": True,
            "can_trade_futures_any": True,
            "spot_requirements": [],
            "futures_requirements": [{"symbol": "BTCUSDT", "min_notional_usd": 5.0}],
        }
        decision = DecisionIntent(
            decision_id="futures-margin-release-test",
            decision_hash="futures-margin-release-hash",
            snapshot_id="futures-margin-release-snapshot",
            config_version="2026-03-12.v1",
            timestamp=now,
            symbol="BTCUSDT",
            candidate_mode="futures",
            final_mode="futures",
            side="long",
            trend_direction=1,
            trend_strength=0.75,
            volume_confirmation=0.72,
            liquidity_score=0.8,
            volatility_penalty=0.52,
            overheat_penalty=0.2,
            predictability_score=72.0,
            gross_expected_edge_bps=24.0,
            net_expected_edge_bps=12.0,
            estimated_round_trip_cost_bps=8.0,
            order_intent_notional_usd=1200.0,
            stop_distance_bps=100.0,
        )

        session._record_decision(decision=decision, state=store.get("BTCUSDT"), timestamp=now)

        self.assertGreaterEqual(live_client.release_calls, 1)
        self.assertEqual(live_client.release_sides[0], "buy")
        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["symbol"], "BTCUSDT")


if __name__ == "__main__":
    unittest.main()
