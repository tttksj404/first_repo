from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_binance.data.state import KlineBar, SymbolMarketState, TopOfBook
from quant_binance.execution.router import ExecutionRouter
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.service import PaperTradingService
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


def make_history() -> FeatureHistoryContext:
    return FeatureHistoryContext(
        returns_1h=(0.0,) * 5,
        returns_4h=(0.0,) * 5,
        quote_volume_5m=(1000,) * 5,
        quote_volume_1h=(10000,) * 5,
        realized_vol_1h=(0.1,) * 5,
        realized_vol_4h=(0.1,) * 5,
        funding_abs=(0.0001, 0.0002, 0.0003, 0.0004, 0.0005),
        basis_abs=(2.0, 3.0, 4.0, 5.0, 6.0),
        oi_surge=(0.05, 0.1, 0.15, 0.2, 0.25),
    )


def make_primitives(*, funding_rate: float) -> PrimitiveInputs:
    return PrimitiveInputs(
        ret_1h=0.0,
        ret_4h=0.0,
        trend_direction=0,
        ema_stack_score=0.0,
        breakout_reference_price=100.0,
        last_trade_price=100.0,
        atr_14_1h_price=2.0,
        quote_volume_5m=1000.0,
        quote_volume_1h=10000.0,
        buy_taker_volume=50.0,
        sell_taker_volume=50.0,
        spread_bps=2.0,
        probe_slippage_bps=3.0,
        depth_usd_within_10bps=300000.0,
        order_book_imbalance_std=0.1,
        realized_vol_1h=0.1,
        realized_vol_4h=0.1,
        median_realized_vol_1h_30d=0.1,
        funding_rate=funding_rate,
        open_interest=1_000_000.0,
        open_interest_ema=1_000_000.0,
        basis_bps=5.0,
        gross_expected_edge_bps=5.0,
    )


def make_state(*, symbol: str, decision_time: datetime, funding_rate: float, last_trade_price: float) -> SymbolMarketState:
    bars = []
    for offset in range(20):
        close_time = decision_time - timedelta(hours=20 - offset)
        bars.append(
            KlineBar(
                symbol=symbol,
                interval="1h",
                start_time=close_time - timedelta(hours=1),
                close_time=close_time,
                open_price=100.0,
                high_price=102.0,
                low_price=98.0,
                close_price=100.0,
                volume=10.0,
                quote_volume=1000.0,
                is_closed=True,
            )
        )
    return SymbolMarketState(
        symbol=symbol,
        top_of_book=TopOfBook(last_trade_price - 0.1, 1.0, last_trade_price + 0.1, 1.0, decision_time),
        last_trade_price=last_trade_price,
        funding_rate=funding_rate,
        open_interest=1_000_000.0,
        basis_bps=5.0,
        last_update_time=decision_time,
        klines={"1h": bars},
        funding_rate_samples=[funding_rate],
        basis_bps_samples=[5.0],
        open_interest_samples=[1_000_000.0],
    )


class QuantBinanceFundingRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_override = os.environ.get("STRATEGY_OVERRIDE_PATH")
        self.settings = Settings.load(CONFIG_PATH)

    def tearDown(self) -> None:
        if self._old_override is None:
            os.environ.pop("STRATEGY_OVERRIDE_PATH", None)
        else:
            os.environ["STRATEGY_OVERRIDE_PATH"] = self._old_override

    def _service_with_override(self) -> PaperTradingService:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json") as handle:
            json.dump(
                {
                    "funding_rate_strategy": {
                        "enabled": True,
                        "threshold": 0.00015,
                        "max_hold_hours": 8,
                        "symbols": ["BTCUSDT"],
                        "notional_usd_per_trade": 50.0,
                    }
                },
                handle,
            )
            override_path = handle.name
        os.environ["STRATEGY_OVERRIDE_PATH"] = override_path
        return PaperTradingService(self.settings, router=ExecutionRouter())

    def test_funding_strategy_blocks_normal_strategy_when_idle(self) -> None:
        service = self._service_with_override()
        now = datetime(2026, 4, 12, 0, 0, tzinfo=timezone.utc)
        decision = service.run_cycle(
            state=make_state(symbol="BTCUSDT", decision_time=now, funding_rate=0.0, last_trade_price=100.0),
            primitive_inputs=make_primitives(funding_rate=0.0),
            history=make_history(),
            decision_time=now,
            equity_usd=1000.0,
            remaining_portfolio_capacity_usd=500.0,
        )
        self.assertEqual(decision.final_mode, "cash")
        self.assertIn("FUNDING_RATE_STRATEGY_IDLE", decision.rejection_reasons)

    def test_funding_strategy_opens_and_exits_through_service(self) -> None:
        service = self._service_with_override()
        entry_time = datetime(2026, 4, 12, 0, 0, tzinfo=timezone.utc)
        entry_decision = service.run_cycle(
            state=make_state(symbol="BTCUSDT", decision_time=entry_time, funding_rate=0.0002, last_trade_price=100.0),
            primitive_inputs=make_primitives(funding_rate=0.0002),
            history=make_history(),
            decision_time=entry_time,
            equity_usd=1000.0,
            remaining_portfolio_capacity_usd=500.0,
        )
        self.assertEqual(entry_decision.final_mode, "futures")
        self.assertEqual(entry_decision.side, "short")
        self.assertEqual(entry_decision.divergence_code, "FUNDING_RATE_STRATEGY")

        exit_time = entry_time + timedelta(hours=1)
        exit_decision = service.run_cycle(
            state=make_state(symbol="BTCUSDT", decision_time=exit_time, funding_rate=0.0002, last_trade_price=105.0),
            primitive_inputs=make_primitives(funding_rate=0.0002),
            history=make_history(),
            decision_time=exit_time,
            equity_usd=1000.0,
            remaining_portfolio_capacity_usd=500.0,
        )
        self.assertEqual(exit_decision.final_mode, "cash")
        self.assertIn("FUNDING_", exit_decision.exit_reason_code)


if __name__ == "__main__":
    unittest.main()
