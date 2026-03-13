from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_binance.backtest.comparison import (
    DirectionalHoldBaselineService,
    compare_strategies,
    render_compact_report,
    write_comparison_report,
)
from quant_binance.backtest.paper_live_fixtures import PaperLiveCycle
from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


def make_history() -> dict[str, list[float]]:
    return {
        "returns_1h": [0.01, 0.015, 0.02, 0.025, 0.03],
        "returns_4h": [0.02, 0.025, 0.03, 0.035, 0.04],
        "quote_volume_5m": [900, 1000, 1100, 1200, 1300],
        "quote_volume_1h": [9000, 9500, 10000, 10500, 11000],
        "realized_vol_1h": [0.08, 0.09, 0.1, 0.11, 0.12],
        "realized_vol_4h": [0.12, 0.13, 0.14, 0.15, 0.16],
        "funding_abs": [0.0001, 0.00015, 0.0002, 0.00025, 0.0003],
        "basis_abs": [1.0, 2.0, 3.0, 4.0, 5.0],
        "oi_surge": [0.03, 0.05, 0.08, 0.1, 0.12],
    }


def make_cycle(
    *,
    decision_time: datetime,
    price: float,
    ret_1h: float,
    ret_4h: float,
    trend_direction: int,
    breakout_reference_price: float,
) -> dict[str, object]:
    return {
        "decision_time": decision_time.isoformat(),
        "symbol": "BTCUSDT",
        "state": {
            "top_of_book": {
                "bid_price": round(price - 0.1, 6),
                "bid_qty": 1.0,
                "ask_price": round(price + 0.1, 6),
                "ask_qty": 1.1,
                "updated_at": decision_time.isoformat(),
            },
            "last_trade_price": price,
            "funding_rate": 0.0001,
            "open_interest": 1080000.0,
            "basis_bps": 2.0,
            "last_update_time": decision_time.isoformat(),
        },
        "primitive_inputs": {
            "ret_1h": ret_1h,
            "ret_4h": ret_4h,
            "trend_direction": trend_direction,
            "ema_stack_score": 1.0 if trend_direction >= 0 else 0.0,
            "breakout_reference_price": breakout_reference_price,
            "last_trade_price": price,
            "atr_14_1h_price": 1.5,
            "quote_volume_5m": 1600.0,
            "quote_volume_1h": 13000.0,
            "buy_taker_volume": 72.0 if trend_direction >= 0 else 34.0,
            "sell_taker_volume": 28.0 if trend_direction >= 0 else 66.0,
            "spread_bps": 2.0,
            "probe_slippage_bps": 2.5,
            "depth_usd_within_10bps": 320000.0,
            "order_book_imbalance_std": 0.08,
            "realized_vol_1h": 0.09,
            "realized_vol_4h": 0.13,
            "median_realized_vol_1h_30d": 0.09,
            "funding_rate": 0.0001,
            "open_interest": 1080000.0,
            "open_interest_ema": 1000000.0,
            "basis_bps": 2.0,
            "gross_expected_edge_bps": 28.0,
        },
        "history": make_history(),
    }


def make_runtime_cycle(
    *,
    decision_time: datetime,
    price: float,
    ret_1h: float,
    ret_4h: float,
    trend_direction: int,
    breakout_reference_price: float,
) -> PaperLiveCycle:
    return PaperLiveCycle(
        decision_time=decision_time,
        symbol="BTCUSDT",
        state=SymbolMarketState(
            symbol="BTCUSDT",
            top_of_book=TopOfBook(
                bid_price=price - 0.1,
                bid_qty=1.0,
                ask_price=price + 0.1,
                ask_qty=1.1,
                updated_at=decision_time,
            ),
            last_trade_price=price,
            funding_rate=0.0001,
            open_interest=1080000.0,
            basis_bps=2.0,
            last_update_time=decision_time,
        ),
        primitive_inputs=PrimitiveInputs(
            ret_1h=ret_1h,
            ret_4h=ret_4h,
            trend_direction=trend_direction,
            ema_stack_score=1.0 if trend_direction >= 0 else 0.0,
            breakout_reference_price=breakout_reference_price,
            last_trade_price=price,
            atr_14_1h_price=1.5,
            quote_volume_5m=1600.0,
            quote_volume_1h=13000.0,
            buy_taker_volume=72.0 if trend_direction >= 0 else 34.0,
            sell_taker_volume=28.0 if trend_direction >= 0 else 66.0,
            spread_bps=2.0,
            probe_slippage_bps=2.5,
            depth_usd_within_10bps=320000.0,
            order_book_imbalance_std=0.08,
            realized_vol_1h=0.09,
            realized_vol_4h=0.13,
            median_realized_vol_1h_30d=0.09,
            funding_rate=0.0001,
            open_interest=1080000.0,
            open_interest_ema=1000000.0,
            basis_bps=2.0,
            gross_expected_edge_bps=28.0,
        ),
        history=FeatureHistoryContext(
            returns_1h=(0.01, 0.015, 0.02, 0.025, 0.03),
            returns_4h=(0.02, 0.025, 0.03, 0.035, 0.04),
            quote_volume_5m=(900, 1000, 1100, 1200, 1300),
            quote_volume_1h=(9000, 9500, 10000, 10500, 11000),
            realized_vol_1h=(0.08, 0.09, 0.1, 0.11, 0.12),
            realized_vol_4h=(0.12, 0.13, 0.14, 0.15, 0.16),
            funding_abs=(0.0001, 0.00015, 0.0002, 0.00025, 0.0003),
            basis_abs=(1.0, 2.0, 3.0, 4.0, 5.0),
            oi_surge=(0.03, 0.05, 0.08, 0.1, 0.12),
        ),
    )


class QuantBinanceComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.settings = Settings.load(CONFIG_PATH)

    def setUp(self) -> None:
        self.fixture_path = ROOT / "tests" / "tmp_paper_live_comparison_fixture.json"
        self.output_path = ROOT / "tests" / "tmp_strategy_comparison_report.json"
        start = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        cycles = [
            make_cycle(
                decision_time=start + timedelta(minutes=5 * offset),
                price=price,
                ret_1h=ret_1h,
                ret_4h=ret_4h,
                trend_direction=trend_direction,
                breakout_reference_price=breakout_reference_price,
            )
            for offset, price, ret_1h, ret_4h, trend_direction, breakout_reference_price in (
                (0, 100.0, 0.015, 0.02, 1, 99.0),
                (1, 103.0, 0.03, 0.04, 1, 100.0),
                (2, 106.0, 0.04, 0.05, 1, 101.0),
                (3, 102.0, -0.015, -0.01, -1, 104.0),
                (4, 98.0, -0.03, -0.04, -1, 102.0),
                (5, 101.0, 0.015, 0.02, 1, 99.0),
            )
        ]
        self.fixture_path.write_text(json.dumps({"cycles": cycles}, indent=2), encoding="utf-8")

    def tearDown(self) -> None:
        if self.fixture_path.exists():
            self.fixture_path.unlink()
        if self.output_path.exists():
            self.output_path.unlink()

    def test_directional_hold_keeps_initial_side_per_symbol(self) -> None:
        service = DirectionalHoldBaselineService(self.settings)
        start = datetime(2026, 3, 8, 12, 5, tzinfo=timezone.utc)
        first = make_runtime_cycle(
            decision_time=start,
            price=100.0,
            ret_1h=0.015,
            ret_4h=0.02,
            trend_direction=1,
            breakout_reference_price=99.0,
        )
        second = make_runtime_cycle(
            decision_time=start + timedelta(minutes=5),
            price=98.0,
            ret_1h=-0.03,
            ret_4h=-0.04,
            trend_direction=-1,
            breakout_reference_price=101.0,
        )
        first_decision = service.run_cycle(
            state=first.state,
            primitive_inputs=first.primitive_inputs,
            history=first.history,
            decision_time=first.decision_time,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        second_decision = service.run_cycle(
            state=second.state,
            primitive_inputs=second.primitive_inputs,
            history=second.history,
            decision_time=second.decision_time,
            equity_usd=10000.0,
            remaining_portfolio_capacity_usd=5000.0,
        )
        self.assertEqual(first_decision.side, "long")
        self.assertEqual(second_decision.side, "long")
        self.assertEqual(first_decision.final_mode, "futures")
        self.assertGreater(first_decision.order_intent_notional_usd, 0.0)

    def test_compare_strategies_returns_default_strategy_set(self) -> None:
        report = compare_strategies(
            config_path=CONFIG_PATH,
            fixture_path=self.fixture_path,
            equity_usd=10000.0,
            capacity_usd=5000.0,
        )
        self.assertEqual(report.cycle_count, 6)
        self.assertEqual(
            [item.strategy_name for item in report.strategies],
            [
                "current_strategy",
                "directional_hold",
                "simple_momentum",
                "simple_mean_reversion",
            ],
        )
        momentum = next(item for item in report.strategies if item.strategy_name == "simple_momentum")
        self.assertGreater(momentum.trade_count, 0)
        self.assertGreaterEqual(momentum.turnover_usd, momentum.entry_turnover_usd)
        self.assertGreaterEqual(momentum.max_drawdown_pct, 0.0)
        self.assertGreaterEqual(momentum.open_position_count, 0)

    def test_report_render_and_json_output_include_baselines(self) -> None:
        report = compare_strategies(
            config_path=CONFIG_PATH,
            fixture_path=self.fixture_path,
            equity_usd=10000.0,
            capacity_usd=5000.0,
        )
        rendered = render_compact_report(report)
        self.assertIn("Strategy comparison", rendered)
        self.assertIn("directional_hold", rendered)
        self.assertIn("simple_momentum", rendered)
        self.assertIn("simple_mean_reversion", rendered)
        self.assertIn("max_dd%", rendered)
        write_comparison_report(self.output_path, report)
        payload = json.loads(self.output_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["cycle_count"], 6)
        self.assertEqual(len(payload["strategies"]), 4)


if __name__ == "__main__":
    unittest.main()
