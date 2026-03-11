from __future__ import annotations

import unittest
from pathlib import Path

from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs
from quant_binance.strategy_profile_switch import AutoProfileSwitchPolicy, AutoProfileSwitcher


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


def _history() -> FeatureHistoryContext:
    return FeatureHistoryContext(
        returns_1h=(0.002, 0.004, 0.006, 0.008, 0.010),
        returns_4h=(0.004, 0.006, 0.008, 0.010, 0.012),
        quote_volume_5m=(1000.0, 1100.0, 1200.0, 1300.0, 1400.0),
        quote_volume_1h=(10000.0, 10200.0, 10400.0, 10600.0, 10800.0),
        realized_vol_1h=(0.004, 0.005, 0.006, 0.007, 0.008),
        realized_vol_4h=(0.005, 0.006, 0.007, 0.008, 0.009),
        funding_abs=(0.0001, 0.00015, 0.0002),
        basis_abs=(2.0, 2.5, 3.0),
        oi_surge=(0.02, 0.03, 0.04),
    )


def _primitive(ret_1h: float) -> PrimitiveInputs:
    return PrimitiveInputs(
        ret_1h=ret_1h,
        ret_4h=0.01,
        trend_direction=1,
        ema_stack_score=1.0,
        breakout_reference_price=100.0,
        last_trade_price=101.0,
        atr_14_1h_price=1.2,
        quote_volume_5m=1400.0,
        quote_volume_1h=10800.0,
        buy_taker_volume=70.0,
        sell_taker_volume=30.0,
        spread_bps=2.0,
        probe_slippage_bps=3.0,
        depth_usd_within_10bps=500000.0,
        order_book_imbalance_std=0.08,
        realized_vol_1h=0.01,
        realized_vol_4h=0.02,
        median_realized_vol_1h_30d=0.01,
        funding_rate=0.0001,
        open_interest=1000000.0,
        open_interest_ema=980000.0,
        basis_bps=2.0,
        gross_expected_edge_bps=20.0,
    )


class QuantBinanceAutoProfileSwitchTests(unittest.TestCase):
    def test_switches_to_fast_profile_on_large_abs_return(self) -> None:
        switcher = AutoProfileSwitcher(
            config_path=CONFIG_PATH,
            policy=AutoProfileSwitchPolicy(
                calm_profile="aggressive_alt",
                fast_profile="scalp_ultra",
                min_hold_cycles=1,
                fast_on_volatility_penalty=1.0,
                fast_off_volatility_penalty=1.0,
                fast_on_abs_ret_1h=0.02,
                fast_off_abs_ret_1h=0.005,
            ),
            runtime_decision_interval_minutes=5,
            initial_profile="aggressive_alt",
        )
        decision = switcher.evaluate(
            primitive_inputs=_primitive(ret_1h=0.03),
            history=_history(),
            cycle_key="2026-03-11T07:15:00+00:00",
        )
        self.assertTrue(decision.changed)
        self.assertEqual(decision.active_profile, "scalp_ultra")
        self.assertEqual(switcher.active_settings.strategy_profile, "scalp_ultra")

    def test_min_hold_cycles_blocks_immediate_flip_back(self) -> None:
        switcher = AutoProfileSwitcher(
            config_path=CONFIG_PATH,
            policy=AutoProfileSwitchPolicy(
                calm_profile="aggressive_alt",
                fast_profile="scalp_ultra",
                min_hold_cycles=2,
                fast_on_volatility_penalty=1.0,
                fast_off_volatility_penalty=1.0,
                fast_on_abs_ret_1h=0.02,
                fast_off_abs_ret_1h=0.005,
            ),
            runtime_decision_interval_minutes=5,
            initial_profile="aggressive_alt",
        )
        to_fast = switcher.evaluate(
            primitive_inputs=_primitive(ret_1h=0.03),
            history=_history(),
            cycle_key="2026-03-11T07:15:00+00:00",
        )
        self.assertTrue(to_fast.changed)
        blocked = switcher.evaluate(
            primitive_inputs=_primitive(ret_1h=0.001),
            history=_history(),
            cycle_key="2026-03-11T07:20:00+00:00",
        )
        self.assertFalse(blocked.changed)
        self.assertEqual(blocked.reason, "MIN_HOLD_LOCK")
        still_blocked = switcher.evaluate(
            primitive_inputs=_primitive(ret_1h=0.001),
            history=_history(),
            cycle_key="2026-03-11T07:25:00+00:00",
        )
        self.assertFalse(still_blocked.changed)
        self.assertEqual(still_blocked.reason, "MIN_HOLD_LOCK")
        to_calm = switcher.evaluate(
            primitive_inputs=_primitive(ret_1h=0.001),
            history=_history(),
            cycle_key="2026-03-11T07:30:00+00:00",
        )
        self.assertTrue(to_calm.changed)
        self.assertEqual(to_calm.active_profile, "aggressive_alt")

    def test_profile_settings_are_coerced_to_runtime_interval(self) -> None:
        switcher = AutoProfileSwitcher(
            config_path=CONFIG_PATH,
            policy=AutoProfileSwitchPolicy(
                calm_profile="aggressive_alt",
                fast_profile="scalp_ultra",
                min_hold_cycles=0,
                fast_on_volatility_penalty=1.0,
                fast_off_volatility_penalty=1.0,
                fast_on_abs_ret_1h=0.02,
                fast_off_abs_ret_1h=0.005,
            ),
            runtime_decision_interval_minutes=1,
            initial_profile="aggressive_alt",
        )
        self.assertEqual(
            switcher.active_settings.decision_engine.decision_interval_minutes,
            1,
        )
        switcher.evaluate(
            primitive_inputs=_primitive(ret_1h=0.03),
            history=_history(),
            cycle_key="2026-03-11T07:15:00+00:00",
        )
        self.assertEqual(
            switcher.active_settings.decision_engine.decision_interval_minutes,
            1,
        )

    def test_same_cycle_key_does_not_reconsume_hold_budget(self) -> None:
        switcher = AutoProfileSwitcher(
            config_path=CONFIG_PATH,
            policy=AutoProfileSwitchPolicy(
                calm_profile="aggressive_alt",
                fast_profile="scalp_ultra",
                min_hold_cycles=2,
                fast_on_volatility_penalty=1.0,
                fast_off_volatility_penalty=1.0,
                fast_on_abs_ret_1h=0.02,
                fast_off_abs_ret_1h=0.005,
            ),
            runtime_decision_interval_minutes=5,
            initial_profile="aggressive_alt",
        )
        switcher.evaluate(
            primitive_inputs=_primitive(ret_1h=0.03),
            history=_history(),
            cycle_key="2026-03-11T07:15:00+00:00",
        )
        first_same_cycle = switcher.evaluate(
            primitive_inputs=_primitive(ret_1h=0.001),
            history=_history(),
            cycle_key="2026-03-11T07:20:00+00:00",
        )
        self.assertEqual(first_same_cycle.reason, "MIN_HOLD_LOCK")
        second_same_cycle = switcher.evaluate(
            primitive_inputs=_primitive(ret_1h=0.001),
            history=_history(),
            cycle_key="2026-03-11T07:20:00+00:00",
        )
        self.assertEqual(second_same_cycle.reason, "CYCLE_LOCK")
        next_cycle = switcher.evaluate(
            primitive_inputs=_primitive(ret_1h=0.001),
            history=_history(),
            cycle_key="2026-03-11T07:25:00+00:00",
        )
        self.assertEqual(next_cycle.reason, "MIN_HOLD_LOCK")


if __name__ == "__main__":
    unittest.main()
