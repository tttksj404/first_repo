from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.live import EventDispatcher, LivePaperRuntime
from quant_binance.models import DecisionIntent
from quant_binance.service import PaperTradingService
from quant_binance.session import LivePaperSession
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


def make_decision(
    *,
    timestamp: datetime,
    symbol: str,
    final_mode: str = "cash",
    side: str = "long",
    order_intent_notional_usd: float = 0.0,
    stop_distance_bps: float = 0.0,
) -> DecisionIntent:
    return DecisionIntent(
        decision_id=f"decision-{timestamp.isoformat()}-{symbol}",
        decision_hash=f"hash-{timestamp.isoformat()}-{symbol}",
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
        liquidity_score=0.8,
        volatility_penalty=0.2,
        overheat_penalty=0.1,
        predictability_score=82.0,
        gross_expected_edge_bps=28.0,
        net_expected_edge_bps=18.0,
        estimated_round_trip_cost_bps=10.0,
        order_intent_notional_usd=order_intent_notional_usd,
        stop_distance_bps=stop_distance_bps,
    )


class PositionRestClient:
    def __init__(self, positions: list[dict[str, object]]) -> None:
        self._positions = positions

    def get_account(self, *, market: str) -> dict[str, object]:
        return {"market": market, "balance": 1000}

    def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, object]:
        return {"market": market, "orders": []}

    def get_positions(self) -> dict[str, object]:
        return {"positions": list(self._positions)}


class FuturesMismatchConvergenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def _build_session(self, *, symbol: str, last_trade_price: float) -> LivePaperSession:
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
            rest_client=PositionRestClient([]),
        )

    def test_reconciled_exchange_position_survives_local_exit_paths(self) -> None:
        session = self._build_session(symbol="BTCUSDT", last_trade_price=100.0)
        session.rest_client = PositionRestClient(
            [
                {
                    "symbol": "BTCUSDT",
                    "holdSide": "long",
                    "total": "0.02",
                    "available": "0.02",
                    "openPriceAvg": "100.0",
                    "markPrice": "100.0",
                    "leverage": "5",
                    "cTime": "1772971200000",
                }
            ]
        )

        session.sync_account()
        session.sync_account()
        position = session.paper_positions["BTCUSDT"]
        self.assertTrue(position.exchange_synced)

        state = session.runtime.dispatcher.store.get("BTCUSDT")
        assert state is not None
        state.last_trade_price = 95.0
        now = datetime(2026, 3, 8, 12, 15, tzinfo=timezone.utc)
        session._record_decision(
            decision=make_decision(timestamp=now, symbol="BTCUSDT"),
            state=state,
            timestamp=now,
        )

        self.assertIn("BTCUSDT", session.paper_positions)
        self.assertEqual(session.closed_trades, [])
        self.assertEqual(session.paper_positions["BTCUSDT"].current_price, 95.0)

    def test_restore_marks_legacy_placeholder_as_exchange_synced_and_keeps_it_open(self) -> None:
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

        state = session.runtime.dispatcher.store.get("ETHUSDT")
        assert state is not None
        state.last_trade_price = 2125.0
        now = datetime(2026, 3, 8, 12, 15, tzinfo=timezone.utc)
        session._record_decision(
            decision=make_decision(timestamp=now, symbol="ETHUSDT", side="short"),
            state=state,
            timestamp=now,
        )

        self.assertIn("ETHUSDT", session.paper_positions)
        self.assertEqual(session.closed_trades, [])


if __name__ == "__main__":
    unittest.main()
