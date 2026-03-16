from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quant_binance.cost_calibration import build_cost_calibration, load_cost_calibration, write_cost_calibration


class QuantBinanceCostCalibrationTests(unittest.TestCase):
    def test_build_cost_calibration_uses_fill_fee_and_reference_price(self) -> None:
        calibration = build_cost_calibration(
            fill_rows=[
                {
                    "symbol": "BTCUSDT",
                    "orderId": "o-1",
                    "price": "70200",
                    "quoteVolume": "35.1",
                    "feeDetail": [{"totalFee": "-0.01404"}],
                },
                {
                    "symbol": "BTCUSDT",
                    "orderId": "o-2",
                    "price": "70300",
                    "quoteVolume": "35.15",
                    "feeDetail": [{"totalFee": "-0.01406"}],
                },
            ],
            order_refs={
                "o-1": {"symbol": "BTCUSDT", "reference_price": 70190.0},
                "o-2": {"symbol": "BTCUSDT", "reference_price": 70270.0},
            },
            lookback_hours=48,
        )
        btc = calibration.for_symbol("BTCUSDT")
        self.assertGreater(btc.empirical_fee_bps, 3.9)
        self.assertGreater(btc.empirical_entry_slippage_bps, 0.0)
        self.assertEqual(btc.fee_sample_count, 2)
        self.assertEqual(btc.slippage_sample_count, 2)

    def test_write_and_load_cost_calibration_round_trip(self) -> None:
        calibration = build_cost_calibration(
            fill_rows=[
                {
                    "symbol": "ETHUSDT",
                    "orderId": "o-1",
                    "price": "2100",
                    "quoteVolume": "42.0",
                    "feeDetail": [{"totalFee": "-0.0168"}],
                }
            ],
            order_refs={"o-1": {"symbol": "ETHUSDT", "reference_price": 2098.0}},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cost_calibration.json"
            write_cost_calibration(calibration=calibration, output_path=path)
            loaded = load_cost_calibration(path)
        assert loaded is not None
        self.assertAlmostEqual(
            loaded.for_symbol("ETHUSDT").empirical_fee_bps,
            calibration.for_symbol("ETHUSDT").empirical_fee_bps,
        )


if __name__ == "__main__":
    unittest.main()
