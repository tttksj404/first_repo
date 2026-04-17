from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.bitget_rest import BitgetRestClient
from quant_binance.execution.router import ExecutionRouter
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.service import PaperTradingService
from quant_binance.session import LivePaperSession
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


class ManualAdoptionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def _build_session(self, *, symbol: str = "BTCUSDT", last_trade_price: float = 50000.0) -> LivePaperSession:
        now = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        store = MarketStateStore()
        store.put(
            SymbolMarketState(
                symbol=symbol,
                top_of_book=TopOfBook(last_trade_price - 0.5, 1.0, last_trade_price + 0.5, 1.2, now),
                last_trade_price=last_trade_price,
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
        return LivePaperSession(
            runtime=runtime,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
            rest_client=None,
            sync_interval_seconds=1,
        )

    @patch("quant_binance.session.send_telegram_message")
    def test_restore_keeps_strategy_owned_live_position_managed_for_one_way_partial_close(self, mock_send) -> None:
        class PositionRestClient(BitgetRestClient):
            def __init__(self) -> None:
                super().__init__(credentials=None)
                self.placed_orders: list[tuple[str, dict[str, object]]] = []
                self.tpsl_orders: list[dict[str, object]] = []

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
                return {"status": "SUCCESS", "orderId": "close-restored-one-way"}

            def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
                self.tpsl_orders.append(order_params)
                return {"status": "SUCCESS", "orderId": "tpsl-1"}

        mock_send.return_value = {"ok": True}
        session = self._build_session()
        session.rest_client = PositionRestClient()
        session.live_positions_snapshot = session.rest_client.get_positions()["positions"]

        restored = session.restore_futures_state_from_runtime(
            state_payload={
                "paper_open_futures_positions": [
                    {
                        "symbol": "BTCUSDT",
                        "market": "futures",
                        "side": "long",
                        "entry_time": "2026-03-08T12:00:00+00:00",
                        "entry_price": 70785.78125,
                        "current_price": 70785.78125,
                        "quantity_opened": 0.0016,
                        "quantity_remaining": 0.0016,
                        "stop_distance_bps": 0.0,
                        "active_stop_price": 70785.78125,
                        "entry_predictability_score": 0.0,
                        "entry_liquidity_score": 0.0,
                        "entry_net_expected_edge_bps": 0.0,
                        "entry_estimated_round_trip_cost_bps": 0.0,
                        "latest_predictability_score": 0.0,
                        "latest_liquidity_score": 0.0,
                        "latest_net_expected_edge_bps": 0.0,
                        "latest_estimated_round_trip_cost_bps": 0.0,
                        "latest_decision_time": "2026-03-08T12:00:00+00:00",
                        "entry_planned_leverage": 8,
                        "exchange_synced": True,
                    }
                ]
            },
        )

        self.assertEqual(restored, 1)
        self.assertEqual(session.paper_positions["BTCUSDT"].origin, "strategy")

        session.sync_account()

        self.assertEqual(len(session.live_orders), 1)
        self.assertEqual(session.live_orders[0]["reason"], "LIVE_POSITION_PROACTIVE_PARTIAL_TAKE_PROFIT")
        self.assertEqual(session.live_orders[0]["response"]["orderId"], "close-restored-one-way")
        self.assertEqual(len(session.rest_client.placed_orders), 1)
        self.assertEqual(session.rest_client.placed_orders[0][1]["side"], "sell")
        self.assertEqual(session.rest_client.placed_orders[0][1]["reduceOnly"], "YES")
        self.assertNotIn("tradeSide", session.rest_client.placed_orders[0][1])
        self.assertEqual(len(session.rest_client.tpsl_orders), 1)

    def test_restore_keeps_legacy_external_placeholder_adopted(self) -> None:
        session = self._build_session(symbol="ETHUSDT", last_trade_price=2110.0)
        session.live_positions_snapshot = [
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

        restored = session.restore_futures_state_from_runtime(
            state_payload={
                "paper_open_futures_positions": [
                    {
                        "symbol": "ETHUSDT",
                        "market": "futures",
                        "side": "short",
                        "entry_time": "2026-03-08T12:00:00+00:00",
                        "entry_price": 2100.0,
                        "current_price": 2110.0,
                        "quantity_opened": 0.5,
                        "quantity_remaining": 0.5,
                        "entry_planned_leverage": 5,
                        "stop_distance_bps": 0.0,
                        "entry_predictability_score": 0.0,
                        "entry_liquidity_score": 0.0,
                        "entry_net_expected_edge_bps": 0.0,
                        "entry_estimated_round_trip_cost_bps": 0.0,
                    }
                ]
            },
        )

        self.assertEqual(restored, 1)
        self.assertTrue(session.paper_positions["ETHUSDT"].exchange_synced)
        self.assertEqual(session.paper_positions["ETHUSDT"].origin, "adopted")
        self.assertEqual(session.paper_positions["ETHUSDT"].adoption_source, "runtime_restore_legacy")

    def test_restore_prefers_strategy_recovered_when_recent_live_order_matches_position(self) -> None:
        session = self._build_session(symbol="PEPEUSDT", last_trade_price=0.0000038)
        session.live_orders.append(
            {
                "timestamp": datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc),
                "symbol": "PEPEUSDT",
                "market": "futures",
                "side": "buy",
                "accepted": True,
            }
        )
        restored = session._build_reconciled_paper_position(
            position={
                "symbol": "PEPEUSDT",
                "holdSide": "long",
                "total": "1000",
                "available": "1000",
                "openPriceAvg": "0.0000038",
                "markPrice": "0.00000381",
                "leverage": "30",
                "cTime": "1772971200000",
            },
            startup_recovery=False,
        )
        assert restored is not None
        self.assertEqual(restored.origin, "strategy_recovered")
        self.assertEqual(restored.adoption_source, "")

    def test_pepe_adopted_position_stays_observe_only_for_live_context(self) -> None:
        session = self._build_session(symbol="PEPEUSDT", last_trade_price=0.0000038)
        session.runtime.paper_service.settings = replace(  # type: ignore[assignment]
            session.runtime.paper_service.settings,
            universe=("PEPEUSDT",),
            futures_exposure=replace(
                session.runtime.paper_service.settings.futures_exposure,
                major_symbols=("PEPEUSDT",),
            ),
        )
        restored = session._build_reconciled_paper_position(
            position={
                "symbol": "PEPEUSDT",
                "holdSide": "long",
                "total": "1000",
                "available": "1000",
                "openPriceAvg": "0.0000038",
                "markPrice": "0.00000381",
                "leverage": "30",
                "cTime": "1772971200000",
            },
            startup_recovery=False,
        )
        assert restored is not None
        session.paper_positions["PEPEUSDT"] = restored
        position_dict = {
            "symbol": "PEPEUSDT",
            "holdSide": "long",
            "total": "1000",
            "available": "1000",
        }
        paper_position, mode = session._live_position_management_context(
            position=position_dict,
            now=datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc),
        )
        self.assertIsNotNone(paper_position)
        self.assertIn(mode, {"adopted", "adopted_grace"})

    @patch("quant_binance.session.send_telegram_message")
    def test_pepe_adopted_position_does_not_auto_close_under_live_risk_management(self, mock_send) -> None:
        class PositionRestClient(BitgetRestClient):
            def __init__(self) -> None:
                super().__init__(credentials=None)
                self.placed_orders: list[tuple[str, dict[str, object]]] = []
                self.snapshots = [
                    {
                        "positions": [
                            {
                                "symbol": "PEPEUSDT",
                                "holdSide": "long",
                                "total": "418358000",
                                "available": "418358000",
                                "marginSize": "53.3",
                                "unrealizedPL": "-2.0",
                                "marginRatio": "0.1",
                                "openPriceAvg": "0.00000395278646",
                                "markPrice": "0.0000039462",
                                "leverage": "30",
                                "cTime": "1776392102773",
                                "uTime": "1776392200000",
                            }
                        ]
                    },
                    {
                        "positions": [
                            {
                                "symbol": "PEPEUSDT",
                                "holdSide": "long",
                                "total": "418358000",
                                "available": "418358000",
                                "marginSize": "53.3",
                                "unrealizedPL": "-2.4",
                                "marginRatio": "0.1",
                                "openPriceAvg": "0.00000395278646",
                                "markPrice": "0.0000039448",
                                "leverage": "30",
                                "cTime": "1776392102773",
                                "uTime": "1776392300000",
                            }
                        ]
                    },
                    {
                        "positions": [
                            {
                                "symbol": "PEPEUSDT",
                                "holdSide": "long",
                                "total": "418358000",
                                "available": "418358000",
                                "marginSize": "53.3",
                                "unrealizedPL": "-8.6",
                                "marginRatio": "0.1",
                                "openPriceAvg": "0.00000395278646",
                                "markPrice": "0.0000039324",
                                "leverage": "30",
                                "cTime": "1776392102773",
                                "uTime": "1776392434470",
                            }
                        ]
                    },
                ]
                self.position_calls = 0

            def get_account(self, *, market: str) -> dict[str, object]:
                return {"market": market, "balance": 1000}

            def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, object]:
                return {"market": market, "orders": []}

            def get_positions(self) -> dict[str, object]:
                index = min(self.position_calls, len(self.snapshots) - 1)
                self.position_calls += 1
                return self.snapshots[index]

            def place_order(self, *, market: str, order_params: dict[str, object]) -> dict[str, object]:
                self.placed_orders.append((market, dict(order_params)))
                raise AssertionError("adopted manual position should remain observe-only")

        settings = replace(
            self.settings,
            universe=("PEPEUSDT",),
            futures_exposure=replace(
                self.settings.futures_exposure,
                major_symbols=("PEPEUSDT",),
            ),
            live_position_risk=replace(
                self.settings.live_position_risk,
                long_only_turnaround_mode=True,
                long_disable_standard_stop_loss=True,
                turnaround_abort_roe_percent=-14.0,
                soft_stop_roe_percent=-8.0,
                stop_loss_roe_percent=-10.0,
            ),
        )
        mock_send.return_value = {"ok": True}
        session = self._build_session(symbol="PEPEUSDT", last_trade_price=0.0000039324)
        session.runtime.paper_service.settings = settings  # type: ignore[assignment]
        session.rest_client = PositionRestClient()

        session.sync_account()
        session.sync_account()
        session.sync_account()

        self.assertIn("PEPEUSDT", session.paper_positions)
        self.assertEqual(session.paper_positions["PEPEUSDT"].origin, "adopted")
        self.assertEqual(session.rest_client.placed_orders, [])
        self.assertEqual(session.live_orders, [])


if __name__ == "__main__":
    unittest.main()
