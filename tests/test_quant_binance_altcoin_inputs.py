from __future__ import annotations

import os
import unittest
from pathlib import Path

from quant_binance.models import FeatureVector
from quant_binance.overlays import apply_altcoin_overlay, load_altcoin_inputs


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "quant_binance" / "examples" / "altcoin_inputs.sample.json"


class QuantBinanceAltcoinInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_path = os.environ.get("ALTCOIN_INPUTS_PATH")
        self.old_json = os.environ.get("ALTCOIN_INPUTS_JSON")
        os.environ.pop("ALTCOIN_INPUTS_PATH", None)
        os.environ.pop("ALTCOIN_INPUTS_JSON", None)

    def tearDown(self) -> None:
        if self.old_path is not None:
            os.environ["ALTCOIN_INPUTS_PATH"] = self.old_path
        if self.old_json is not None:
            os.environ["ALTCOIN_INPUTS_JSON"] = self.old_json

    def _features(self) -> FeatureVector:
        return FeatureVector(
            ret_rank_1h=0.8,
            ret_rank_4h=0.8,
            breakout_norm=0.8,
            ema_stack_score=1.0,
            vol_z_5m_norm=0.7,
            vol_z_1h_norm=0.7,
            taker_imbalance_norm=0.7,
            spread_bps_norm=0.2,
            probe_slippage_bps_norm=0.2,
            depth_10bps_norm=0.8,
            book_stability_norm=0.8,
            realized_vol_1h_norm=0.3,
            realized_vol_4h_norm=0.3,
            vol_shock_norm=0.3,
            funding_abs_percentile=0.2,
            oi_surge_percentile=0.2,
            basis_stretch_percentile=0.2,
            regime_alignment=1.0,
            trend_direction=1,
            trend_strength=0.8,
            volume_confirmation=0.7,
            liquidity_score=0.8,
            volatility_penalty=0.3,
            overheat_penalty=0.2,
            gross_expected_edge_bps=30.0,
            estimated_round_trip_cost_bps=10.0,
        )

    def test_load_altcoin_inputs_from_path(self) -> None:
        os.environ["ALTCOIN_INPUTS_PATH"] = str(SAMPLE_PATH)
        alt_inputs = load_altcoin_inputs()
        self.assertIsNotNone(alt_inputs)
        assert alt_inputs is not None
        self.assertAlmostEqual(alt_inputs.global_inputs.alt_breadth_score, 0.58)
        self.assertIn("SOLUSDT", alt_inputs.symbols)

    def test_apply_altcoin_overlay_enriches_alt_symbol(self) -> None:
        os.environ["ALTCOIN_INPUTS_PATH"] = str(SAMPLE_PATH)
        alt_inputs = load_altcoin_inputs()
        enriched = apply_altcoin_overlay(self._features(), symbol="SOLUSDT", altcoin_inputs=alt_inputs)
        self.assertIn(enriched.alt_market_regime, {"risk_on", "neutral"})
        self.assertGreater(enriched.alt_smart_money_score, 0.5)
        self.assertGreater(enriched.alt_fundamental_score, 0.5)

    def test_apply_altcoin_overlay_skips_btc(self) -> None:
        os.environ["ALTCOIN_INPUTS_PATH"] = str(SAMPLE_PATH)
        alt_inputs = load_altcoin_inputs()
        enriched = apply_altcoin_overlay(self._features(), symbol="BTCUSDT", altcoin_inputs=alt_inputs)
        self.assertEqual(enriched.alt_market_regime, "neutral")
        self.assertEqual(enriched.alt_breadth_score, 0.5)


if __name__ == "__main__":
    unittest.main()
