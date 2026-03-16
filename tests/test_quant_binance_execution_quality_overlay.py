from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from quant_binance.data.market_store import MarketStateStore
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.execution.live_order_adapter import DecisionLiveOrderAdapter
from quant_binance.execution_quality import ExecutionQualityState
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
    symbol: str = "BTCUSDT",
    final_mode: str = "futures",
    side: str = "long",
    net_expected_edge_bps: float = 18.0,
    order_intent_notional_usd: float = 1000.0,
) -> DecisionIntent:
    return DecisionIntent(
        decision_id=f"decision-{timestamp.isoformat()}",
        decision_hash=f"hash-{timestamp.isoformat()}",
        snapshot_id=f"snapshot-{timestamp.isoformat()}",
        config_version="2026-03-16.v1",
        timestamp=timestamp,
        symbol=symbol,
        candidate_mode="futures",
        final_mode=final_mode,
        side=side,
        trend_direction=1 if side == "long" else -1,
        trend_strength=0.82,
        volume_confirmation=0.76,
        liquidity_score=0.84,
        volatility_penalty=0.2,
        overheat_penalty=0.1,
        predictability_score=84.0,
        gross_expected_edge_bps=28.0,
        net_expected_edge_bps=net_expected_edge_bps,
        estimated_round_trip_cost_bps=10.0,
        order_intent_notional_usd=order_intent_notional_usd,
        stop_distance_bps=45.0,
    )


class PartialFillLiveOrderClient:
    def __init__(self) -> None:
        self.exchange_id = "binance"

    def set_futures_leverage(self, *, symbol, leverage):  # type: ignore[no-untyped-def]
        return {"symbol": symbol, "leverage": leverage}

    def place_order(self, *, market, order_params):  # type: ignore[no-untyped-def]
        return {
            "status": "PARTIALLY_FILLED",
            "market": market,
            "orderId": "partial-1",
            "executedQty": "0.01",
            "cummulativeQuoteQty": "505.0",
            "avgPrice": "50500.0",
        }

    def place_futures_position_tpsl(self, *, order_params):  # type: ignore[no-untyped-def]
        return {"status": "SUCCESS", "orderId": "tpsl-1"}

    def place_spot_plan_order(self, *, order_params):  # type: ignore[no-untyped-def]
        return {"status": "SUCCESS", "orderId": "spot-plan-1"}

    def get_max_openable_quantity(self, *, symbol, pos_side, order_type="market", open_amount=None):  # type: ignore[no-untyped-def]
        return None


class QuantBinanceExecutionQualityOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def _build_runtime(self, now: datetime) -> tuple[LivePaperRuntime, SymbolMarketState]:
        state = SymbolMarketState(
            symbol="BTCUSDT",
            top_of_book=TopOfBook(49999.5, 1.0, 50000.5, 1.2, now),
            last_trade_price=50000.0,
            funding_rate=0.0001,
            open_interest=1000000.0,
            basis_bps=3.0,
            last_update_time=now,
        )
        store = MarketStateStore()
        store.put(state)
        runtime = LivePaperRuntime(
            dispatcher=EventDispatcher(store),
            paper_service=PaperTradingService(self.settings),
            primitive_builder=lambda symbol, decision_time: None,  # type: ignore[return-value]
            history_provider=lambda symbol, decision_time: None,  # type: ignore[return-value]
            decision_interval_minutes=self.settings.decision_engine.decision_interval_minutes,
        )
        return runtime, state

    def test_overlay_is_neutral_below_minimum_sample_size(self) -> None:
        state = ExecutionQualityState()
        state.record(
            symbol="BTCUSDT",
            outcome="partial_fill",
            fill_ratio=0.5,
            slippage_bps=9.0,
            realized_edge_bps=2.0,
            timestamp=datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc),
        )
        state.record(
            symbol="BTCUSDT",
            outcome="reject",
            fill_ratio=0.0,
            slippage_bps=None,
            realized_edge_bps=0.0,
            timestamp=datetime(2026, 3, 16, 0, 5, tzinfo=timezone.utc),
        )

        decision = state.apply_overlay(
            make_decision(timestamp=datetime(2026, 3, 16, 0, 10, tzinfo=timezone.utc))
        )

        self.assertEqual(decision.final_mode, "futures")
        self.assertEqual(decision.order_intent_notional_usd, 1000.0)
        self.assertEqual(decision.net_expected_edge_bps, 18.0)
        self.assertEqual(decision.execution_quality_sample_size, 2)

    def test_overlay_reduces_size_and_restrains_when_quality_is_degraded(self) -> None:
        state = ExecutionQualityState()
        for minute in range(3):
            state.record(
                symbol="BTCUSDT",
                outcome="timeout",
                fill_ratio=0.0,
                slippage_bps=None,
                realized_edge_bps=0.0,
                timestamp=datetime(2026, 3, 16, 1, minute * 5, tzinfo=timezone.utc),
            )

        restrained = state.apply_overlay(
            make_decision(timestamp=datetime(2026, 3, 16, 1, 20, tzinfo=timezone.utc))
        )

        self.assertEqual(restrained.final_mode, "cash")
        self.assertEqual(restrained.side, "flat")
        self.assertEqual(restrained.order_intent_notional_usd, 0.0)
        self.assertEqual(restrained.execution_quality_trade_restraint, "execution_quality_halt")
        self.assertIn("EXECUTION_QUALITY_RESTRAINT", restrained.rejection_reasons)

    def test_session_records_partial_fill_metrics_and_flushes_execution_quality_snapshot(self) -> None:
        now = datetime(2026, 3, 16, 2, 0, tzinfo=timezone.utc)
        runtime, state = self._build_runtime(now)
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir)
            summary_path = base / "output" / "paper-live-shell" / "run-a" / "summary.json"
            state_path = base / "output" / "paper-live-shell" / "run-a" / "summary.state.json"
            execution_quality_state_path = base / "execution_quality_state.json"
            session = LivePaperSession(
                runtime=runtime,
                equity_usd=10000.0,
                remaining_portfolio_capacity_usd=5000.0,
                live_order_executor=DecisionLiveOrderAdapter(PartialFillLiveOrderClient(), self.settings),  # type: ignore[arg-type]
                execution_quality_state_path=execution_quality_state_path,
            )

            session._record_decision(
                decision=make_decision(timestamp=now),
                state=state,
                timestamp=now,
            )
            summary = session.flush(summary_path=summary_path, state_path=state_path)

            live_order = session.live_orders[0]
            self.assertEqual(live_order["fill_status"], "partial_fill")
            self.assertAlmostEqual(float(live_order["fill_ratio"]), 0.5, places=6)
            self.assertGreater(float(live_order["slippage_bps"]), 0.0)

            persisted = json.loads(execution_quality_state_path.read_text(encoding="utf-8"))
            metrics = persisted["symbols"]["BTCUSDT"]
            self.assertEqual(metrics["attempts"], 1)
            self.assertEqual(metrics["partial_fills"], 1)
            self.assertAlmostEqual(float(metrics["avg_fill_ratio"]), 0.5, places=6)

            self.assertIn("execution_quality", summary)
            self.assertIn("BTCUSDT", summary["execution_quality"]["symbols"])
            summary_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("execution_quality", summary_state)
            self.assertEqual(summary_state["execution_quality"]["symbols"]["BTCUSDT"]["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
