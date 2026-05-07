from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COUNTERFACTUAL_PATH = ROOT / "scripts" / "quant_paper50_counterfactual.py"
DIAGNOSIS_PATH = ROOT / "scripts" / "quant_paper50_entry_diagnosis.py"
OUTCOMES_PATH = ROOT / "scripts" / "quant_paper50_entry_outcomes.py"
FUTURES_SIGNAL_OUTCOMES_PATH = ROOT / "scripts" / "quant_paper50_futures_signal_outcomes.py"
DELAYED_ENTRY_EXPERIMENT_PATH = ROOT / "scripts" / "quant_paper50_delayed_entry_experiment.py"
BLOCK_REASON_VALIDATION_PATH = ROOT / "scripts" / "quant_paper50_block_reason_validation.py"

spec = importlib.util.spec_from_file_location("quant_paper50_counterfactual", COUNTERFACTUAL_PATH)
counterfactual = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(counterfactual)

diagnosis_spec = importlib.util.spec_from_file_location("quant_paper50_entry_diagnosis", DIAGNOSIS_PATH)
entry_diagnosis = importlib.util.module_from_spec(diagnosis_spec)
assert diagnosis_spec is not None and diagnosis_spec.loader is not None
diagnosis_spec.loader.exec_module(entry_diagnosis)

outcomes_spec = importlib.util.spec_from_file_location("quant_paper50_entry_outcomes", OUTCOMES_PATH)
entry_outcomes = importlib.util.module_from_spec(outcomes_spec)
assert outcomes_spec is not None and outcomes_spec.loader is not None
outcomes_spec.loader.exec_module(entry_outcomes)

futures_signal_spec = importlib.util.spec_from_file_location(
    "quant_paper50_futures_signal_outcomes",
    FUTURES_SIGNAL_OUTCOMES_PATH,
)
futures_signal_outcomes = importlib.util.module_from_spec(futures_signal_spec)
assert futures_signal_spec is not None and futures_signal_spec.loader is not None
futures_signal_spec.loader.exec_module(futures_signal_outcomes)

delayed_entry_spec = importlib.util.spec_from_file_location(
    "quant_paper50_delayed_entry_experiment",
    DELAYED_ENTRY_EXPERIMENT_PATH,
)
delayed_entry_experiment = importlib.util.module_from_spec(delayed_entry_spec)
assert delayed_entry_spec is not None and delayed_entry_spec.loader is not None
delayed_entry_spec.loader.exec_module(delayed_entry_experiment)

block_reason_spec = importlib.util.spec_from_file_location(
    "quant_paper50_block_reason_validation",
    BLOCK_REASON_VALIDATION_PATH,
)
block_reason_validation = importlib.util.module_from_spec(block_reason_spec)
assert block_reason_spec is not None and block_reason_spec.loader is not None
block_reason_spec.loader.exec_module(block_reason_validation)


class QuantPaper50ScriptTests(unittest.TestCase):
    def test_default_decision_paths_fall_back_to_paper_live_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = base / "output" / "paper-live-shell" / "20260422-132904" / "logs"
            second = base / "output" / "paper-live-shell" / "20260422-141700" / "logs"
            latest = base / "output" / "paper-live-shell" / "latest" / "logs"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            latest.mkdir(parents=True)
            (first / "decisions.jsonl").write_text("", encoding="utf-8")
            (second / "decisions.jsonl").write_text("", encoding="utf-8")
            (latest / "decisions.jsonl").write_text("", encoding="utf-8")

            paths = counterfactual._default_decision_paths(base)

            self.assertEqual(
                [path.relative_to(base).as_posix() for path in paths],
                [
                    "output/paper-live-shell/20260422-132904/logs/decisions.jsonl",
                    "output/paper-live-shell/20260422-141700/logs/decisions.jsonl",
                ],
            )

    def test_default_decision_paths_prefer_forensics_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            forensics = base / "forensics"
            run_logs = base / "output" / "paper-live-shell" / "20260422-132904" / "logs"
            forensics.mkdir(parents=True)
            run_logs.mkdir(parents=True)
            (forensics / "decisions.jsonl").write_text("", encoding="utf-8")
            (run_logs / "decisions.jsonl").write_text("", encoding="utf-8")

            paths = counterfactual._default_decision_paths(base)

            self.assertEqual(paths, [forensics / "decisions.jsonl"])

    def test_load_decisions_deduplicates_across_run_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = base / "first.jsonl"
            second = base / "second.jsonl"
            row = {
                "decision_id": "same-decision",
                "symbol": "BTCUSDT",
                "timestamp": "2020-01-01T00:00:00+00:00",
            }
            first.write_text(json.dumps(row) + "\n", encoding="utf-8")
            second.write_text(json.dumps(row) + "\n", encoding="utf-8")

            rows = counterfactual._load_decisions(
                [first, second],
                symbols={"BTCUSDT"},
                min_age_minutes=1,
            )

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["decision_id"], "same-decision")

    def test_counterfactual_keeps_blocked_entries_and_skips_executable_entries(self) -> None:
        self.assertTrue(counterfactual._is_blocked_entry({"rejected": True, "final_mode": "cash", "side": "flat"}))
        self.assertTrue(counterfactual._is_blocked_entry({"final_mode": "cash", "side": "flat"}))
        self.assertFalse(
            counterfactual._is_blocked_entry(
                {
                    "rejected": False,
                    "final_mode": "futures",
                    "side": "short",
                    "order_intent_notional_usd": 100.0,
                }
            )
        )

    def test_entry_diagnosis_flags_zero_order_missed_entries_as_too_conservative(self) -> None:
        payload = entry_diagnosis.build_diagnosis(
            counterfactual={
                "decision_count": 100,
                "possible_missed_entry_count": 12,
                "symbol_summaries": {
                    "ETHUSDT": {
                        "decision_count": 20,
                        "label_counts": {"possible_missed_entry": 4, "confirmed_block": 6},
                        "avg_net_after_cost_bps": 8.0,
                        "best_net_after_cost_bps": 50.0,
                        "worst_net_after_cost_bps": -5.0,
                        "verdict": "needs_review",
                    }
                },
            },
            overview={
                "decision_count": 500,
                "live_order_count": 0,
                "tested_order_count": 0,
                "recent_decisions": [{"mode": "cash"}, {"mode": "cash"}],
            },
            filters={"symbol_filter_profiles": {"ETHUSDT": {"min_predictability_score": 68.0}}},
        )

        self.assertEqual(payload["posture"], "too_conservative")
        self.assertEqual(payload["entry_width"], "too_narrow")
        self.assertEqual(payload["recent_cash_ratio"], 1.0)
        self.assertEqual(payload["priority_symbols"], ["ETHUSDT"])

    def test_entry_diagnosis_warns_against_broadening_when_blocks_are_valid(self) -> None:
        payload = entry_diagnosis.build_diagnosis(
            counterfactual={
                "decision_count": 100,
                "possible_missed_entry_count": 0,
                "symbol_summaries": {
                    "BTCUSDT": {
                        "decision_count": 100,
                        "label_counts": {"confirmed_block": 80},
                        "verdict": "healthy",
                    }
                },
            },
            overview={"decision_count": 100, "live_order_count": 0, "tested_order_count": 0},
            filters={"symbol_filter_profiles": {"BTCUSDT": {"min_predictability_score": 78.0}}},
        )

        self.assertEqual(payload["posture"], "selective_not_broad")
        self.assertEqual(payload["symbol_diagnostics"][0]["recommended_action"], "hold_or_tighten_if_orders_appear")

    def test_entry_diagnosis_prioritizes_current_live_paper_entries(self) -> None:
        payload = entry_diagnosis.build_diagnosis(
            counterfactual={
                "decision_count": 100,
                "possible_missed_entry_count": 12,
                "symbol_summaries": {},
            },
            overview={
                "decision_count": 12,
                "live_order_count": 0,
                "tested_order_count": 1,
                "recent_decisions": [{"mode": "futures", "symbol": "BTCUSDT"}, {"mode": "cash", "symbol": "ETHUSDT"}],
            },
            filters={"symbol_filter_profiles": {}},
        )

        self.assertEqual(payload["posture"], "active_entries_pending_outcome")
        self.assertEqual(payload["entry_width"], "not_too_narrow_now")
        self.assertEqual(payload["recent_futures_symbols"], ["BTCUSDT"])

    def test_entry_outcomes_selects_only_executable_accepted_entries(self) -> None:
        rows = [
            {
                "timestamp": "2020-01-01T00:00:00+00:00",
                "rejected": False,
                "final_mode": "futures",
                "side": "short",
                "order_intent_notional_usd": 100.0,
            },
            {
                "timestamp": "2020-01-01T00:00:00+00:00",
                "rejected": False,
                "final_mode": "futures",
                "side": "short",
                "order_intent_notional_usd": 0.0,
            },
            {
                "timestamp": "2020-01-01T00:00:00+00:00",
                "rejected": True,
                "final_mode": "futures",
                "side": "short",
                "order_intent_notional_usd": 100.0,
            },
        ]

        accepted = entry_outcomes._accepted_entries(rows, min_age_minutes=1)

        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]["order_intent_notional_usd"], 100.0)

    def test_entry_outcomes_summarizes_negative_net_returns(self) -> None:
        payload = entry_outcomes._summarize(
            [
                {"symbol": "BTCUSDT", "forward_net_returns_bps": {"net_ret5_bps": -2.0}},
                {"symbol": "BTCUSDT", "forward_net_returns_bps": {"net_ret5_bps": 4.0}},
            ],
            horizons=[5],
        )

        self.assertEqual(payload["accepted_entry_count"], 2)
        self.assertEqual(payload["horizon_summary"]["5m"]["negative_count"], 1)
        self.assertEqual(payload["horizon_summary"]["5m"]["avg_net_bps"], 1.0)

    def test_futures_signal_outcomes_keeps_zero_notional_signals(self) -> None:
        rows = [
            {
                "timestamp": "2020-01-01T00:00:00+00:00",
                "rejected": False,
                "final_mode": "futures",
                "side": "long",
                "order_intent_notional_usd": 0.0,
            },
            {
                "timestamp": "2020-01-01T00:00:00+00:00",
                "rejected": False,
                "final_mode": "futures",
                "side": "short",
                "order_intent_notional_usd": 100.0,
            },
            {
                "timestamp": "2020-01-01T00:00:00+00:00",
                "rejected": True,
                "final_mode": "futures",
                "side": "short",
                "order_intent_notional_usd": 100.0,
            },
        ]

        signals = futures_signal_outcomes._futures_signals(rows, min_age_minutes=1)

        self.assertEqual(len(signals), 2)
        self.assertEqual(signals[0]["order_intent_notional_usd"], 0.0)

    def test_futures_signal_outcomes_summarizes_zero_notional_group(self) -> None:
        payload = futures_signal_outcomes.build_report(
            rows=[
                {
                    "timestamp": "2020-01-01T00:00:00+00:00",
                    "symbol": "BTCUSDT",
                    "rejected": False,
                    "final_mode": "futures",
                    "side": "long",
                    "order_intent_notional_usd": 0.0,
                    "reference_price": 100.0,
                    "estimated_round_trip_cost_bps": 1.0,
                },
                {
                    "timestamp": "2020-01-01T00:00:00+00:00",
                    "symbol": "ETHUSDT",
                    "rejected": False,
                    "final_mode": "futures",
                    "side": "long",
                    "order_intent_notional_usd": 10.0,
                    "reference_price": 100.0,
                    "estimated_round_trip_cost_bps": 1.0,
                },
            ],
            client=type(
                "Client",
                (),
                {
                    "get_klines": lambda self, **kwargs: [
                        {"open_time": 1577836800000, "close_price": 100.0},
                        {"open_time": 1577837100000, "close_price": 101.0},
                    ]
                },
            )(),
            horizons=[5],
            min_age_minutes=1,
        )

        self.assertEqual(payload["summary"]["all_futures_signals"]["count"], 2)
        self.assertEqual(payload["summary"]["zero_notional_futures_signals"]["count"], 1)
        self.assertEqual(payload["summary"]["executable_entries"]["count"], 1)
        self.assertEqual(payload["summary"]["all_futures_signals"]["horizons"]["5m"]["avg"], 99.0)

    def test_delayed_entry_experiment_compares_immediate_and_delayed(self) -> None:
        payload = delayed_entry_experiment.build_report(
            rows=[
                {
                    "timestamp": "2020-01-01T00:00:00+00:00",
                    "symbol": "BTCUSDT",
                    "rejected": False,
                    "final_mode": "futures",
                    "side": "long",
                    "order_intent_notional_usd": 0.0,
                    "reference_price": 100.0,
                    "estimated_round_trip_cost_bps": 1.0,
                    "predictability_score": 80.0,
                    "net_expected_edge_bps": 40.0,
                }
            ],
            client=type(
                "Client",
                (),
                {
                    "get_klines": lambda self, **kwargs: [
                        {"open_time": 1577836800000, "close_price": 100.0},
                        {"open_time": 1577837100000, "close_price": 99.0},
                        {"open_time": 1577837400000, "close_price": 102.0},
                    ]
                },
            )(),
            horizons=[5],
            delay_minutes=5,
            min_age_minutes=1,
        )

        all_signals = payload["summary"]["all_futures_signals"]
        self.assertEqual(all_signals["count"], 1)
        self.assertEqual(all_signals["immediate"]["5m"]["avg"], -101.0)
        self.assertEqual(all_signals["delay_5m"]["5m"]["avg"], 302.030303)

    def test_block_reason_validation_classifies_high_miss_rate_as_watch(self) -> None:
        label_mix = [
            {"label": "possible_missed_entry", "net_after_cost_bps": 20.0},
            {"label": "possible_missed_entry", "net_after_cost_bps": 10.0},
            {"label": "confirmed_block", "net_after_cost_bps": -15.0},
            {"label": "confirmed_block", "net_after_cost_bps": -12.0},
            {"label": "watch_marginal_miss", "net_after_cost_bps": 5.0},
        ]
        summary = block_reason_validation._summarize_evaluated(label_mix)

        self.assertEqual(summary["n"], 5)
        self.assertAlmostEqual(summary["miss_rate"], 0.4)
        self.assertEqual(summary["classification"], "watch_too_conservative")

    def test_block_reason_validation_reason_bucket_counts(self) -> None:
        evaluated = [
            {
                "symbol": "BTCUSDT",
                "label": "confirmed_block",
                "net_after_cost_bps": -10.0,
                "rejection_reasons": ["SCORE_TOO_LOW"],
            },
            {
                "symbol": "BTCUSDT",
                "label": "possible_missed_entry",
                "net_after_cost_bps": 25.0,
                "rejection_reasons": ["SCORE_TOO_LOW", "EDGE_BELOW_COST"],
            },
            {
                "symbol": "ETHUSDT",
                "label": "watch_marginal_miss",
                "net_after_cost_bps": 1.0,
                "rejection_reasons": [],
            },
        ]

        by_reason, by_symbol, by_symbol_reason = block_reason_validation._reason_buckets(evaluated)

        self.assertEqual(by_reason["SCORE_TOO_LOW"]["n"], 2)
        self.assertEqual(by_reason["EDGE_BELOW_COST"]["n"], 1)
        self.assertEqual(by_reason["UNSPECIFIED_BLOCK_REASON"]["n"], 1)
        self.assertEqual(by_symbol["BTCUSDT"]["n"], 2)
        self.assertEqual(by_symbol_reason["BTCUSDT:SCORE_TOO_LOW"]["n"], 2)


if __name__ == "__main__":
    unittest.main()
