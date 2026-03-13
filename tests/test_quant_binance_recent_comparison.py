from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quant_binance.backtest.paper_live_fixtures import load_paper_live_cycles
from quant_binance.backtest.recent_comparison import (
    prepare_recent_comparison_fixture,
    select_best_recent_source,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "quant_binance" / "config.example.json"


def make_closed_5m_event(*, symbol: str, start_time: datetime, open_price: float, close_price: float, quote_volume: float) -> dict[str, object]:
    end_time = start_time + timedelta(minutes=5) - timedelta(milliseconds=1)
    return {
        "payload": {
            "data": {
                "s": symbol,
                "k": {
                    "t": int(start_time.timestamp() * 1000),
                    "T": int(end_time.timestamp() * 1000),
                    "i": "5m",
                    "o": f"{open_price:.6f}",
                    "h": f"{max(open_price, close_price) * 1.001:.6f}",
                    "l": f"{min(open_price, close_price) * 0.999:.6f}",
                    "c": f"{close_price:.6f}",
                    "v": "1000.0",
                    "q": f"{quote_volume:.6f}",
                    "x": True,
                },
            },
            "stream": f"{symbol.lower()}@kline_5m",
        },
        "timestamp": (end_time + timedelta(milliseconds=1)).isoformat(),
    }


def make_decision(*, symbol: str, timestamp: datetime, index: int) -> dict[str, object]:
    return {
        "symbol": symbol,
        "timestamp": timestamp.isoformat(),
        "estimated_round_trip_cost_bps": 8.5 + (index % 3),
        "gross_expected_edge_bps": 18.0 + (index * 0.05),
        "liquidity_score": 0.58,
        "volume_confirmation": 0.63,
        "overheat_penalty": 0.22,
        "trend_direction": 1 if index % 2 == 0 else -1,
    }


class QuantBinanceRecentComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tempdir.name) / "quant_runtime"
        self.mode_root = self.base_dir / "output" / "paper-live-shell"
        self.mode_root.mkdir(parents=True, exist_ok=True)
        self.best_run = self.mode_root / "20260313-062512"
        self.sparse_run = self.mode_root / "20260313-071406"
        self._write_run(
            run_dir=self.best_run,
            symbol="DOGEUSDT",
            bar_count=320,
            decision_indexes=range(244, 260),
            recognized_balance=321.0,
            execution_balance=123.0,
        )
        self._write_run(
            run_dir=self.sparse_run,
            symbol="ETHUSDT",
            bar_count=50,
            decision_indexes=range(30, 40),
            recognized_balance=500.0,
            execution_balance=250.0,
        )
        self.fixture_path = Path(self.tempdir.name) / "recent_fixture.json"
        self.prep_path = Path(self.tempdir.name) / "recent_prep.json"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _write_run(
        self,
        *,
        run_dir: Path,
        symbol: str,
        bar_count: int,
        decision_indexes: range,
        recognized_balance: float,
        execution_balance: float,
    ) -> None:
        logs_dir = run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        start = datetime(2026, 3, 10, 0, 0, tzinfo=UTC)
        events = []
        close_price = 0.09 if symbol == "DOGEUSDT" else 2100.0
        for index in range(bar_count):
            open_price = close_price
            close_price = close_price * (1.0008 if index % 2 == 0 else 0.9995)
            events.append(
                make_closed_5m_event(
                    symbol=symbol,
                    start_time=start + timedelta(minutes=5 * index),
                    open_price=open_price,
                    close_price=close_price,
                    quote_volume=100000.0 + (index * 250.0),
                )
            )
        (logs_dir / "events.jsonl").write_text(
            "\n".join(json.dumps(item) for item in events) + "\n",
            encoding="utf-8",
        )

        decisions = [
            make_decision(
                symbol=symbol,
                timestamp=start + timedelta(minutes=5 * (index + 1)),
                index=index,
            )
            for index in decision_indexes
        ]
        (logs_dir / "decisions.jsonl").write_text(
            "\n".join(json.dumps(item) for item in decisions) + "\n",
            encoding="utf-8",
        )

        capital_report = {
            "futures_recognized_balance_usd": recognized_balance,
            "futures_execution_balance_usd": execution_balance,
        }
        summary = {"capital_report": capital_report}
        state = {"capital_report": capital_report, "updated_at": datetime(2026, 3, 13, 7, 0, tzinfo=UTC).isoformat()}
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        (run_dir / "summary.state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

    def test_select_best_recent_source_prefers_convertible_recent_data(self) -> None:
        source = select_best_recent_source(base_dir=self.base_dir)
        self.assertEqual(Path(source.run_dir).name, "20260313-062512")
        self.assertEqual(source.overlap_symbols, ("DOGEUSDT",))
        self.assertEqual(source.decision_count, 16)
        self.assertEqual(source.convertible_decision_count, 9)

    def test_prepare_recent_comparison_fixture_writes_extended_cycles(self) -> None:
        prepared = prepare_recent_comparison_fixture(
            config_path=CONFIG_PATH,
            base_dir=self.base_dir,
            fixture_path=self.fixture_path,
            preparation_report_path=self.prep_path,
        )
        self.assertEqual(prepared.cycle_count, 9)
        self.assertEqual(prepared.skipped_before_warmup_count, 7)
        self.assertEqual(prepared.equity_usd, 321.0)
        self.assertEqual(prepared.capacity_usd, 123.0)
        self.assertEqual(prepared.symbol_cycle_counts, {"DOGEUSDT": 9})
        self.assertTrue(self.fixture_path.exists())
        self.assertTrue(self.prep_path.exists())

        cycles = load_paper_live_cycles(self.fixture_path)
        self.assertEqual(len(cycles), 9)
        first = cycles[0]
        self.assertIn("5m", first.state.klines)
        self.assertIn("1h", first.state.klines)
        self.assertIn("4h", first.state.klines)
        self.assertEqual(len(first.state.trades), 2)
        self.assertGreaterEqual(len(first.state.klines["1h"]), 21)
        self.assertGreater(first.primitive_inputs.gross_expected_edge_bps, 0.0)
        self.assertNotEqual(first.primitive_inputs.trend_direction, 0)
        prep_payload = json.loads(self.prep_path.read_text(encoding="utf-8"))
        self.assertEqual(prep_payload["source"]["convertible_decision_count"], 9)
        self.assertIn("dense trade tape per decision", prep_payload["missing_inputs"])


if __name__ == "__main__":
    unittest.main()
