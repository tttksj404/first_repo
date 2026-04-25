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
SIDE_SCORECARD_PATH = ROOT / "scripts" / "quant_paper50_side_scorecard.py"
POST_TUNE_FEEDBACK_PATH = ROOT / "scripts" / "quant_paper50_post_tune_feedback.py"
MARKET_REGIME_PATH = ROOT / "scripts" / "quant_paper50_market_regime.py"
PROMOTION_CHECKLIST_PATH = ROOT / "scripts" / "quant_paper50_promotion_checklist.py"
MAJOR_5M_RESEARCH_PATH = ROOT / "scripts" / "quant_major_5m_leverage_research.py"
FORCED_PILOT_PATH = ROOT / "scripts" / "quant_paper50_forced_pilot.py"
PARALLEL_RESEARCH_PATH = ROOT / "scripts" / "quant_paper50_parallel_research.py"
SAMPLE_BOOSTER_PATH = ROOT / "scripts" / "quant_paper50_sample_booster.py"

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

side_scorecard_spec = importlib.util.spec_from_file_location(
    "quant_paper50_side_scorecard",
    SIDE_SCORECARD_PATH,
)
side_scorecard = importlib.util.module_from_spec(side_scorecard_spec)
assert side_scorecard_spec is not None and side_scorecard_spec.loader is not None
side_scorecard_spec.loader.exec_module(side_scorecard)

post_tune_feedback_spec = importlib.util.spec_from_file_location(
    "quant_paper50_post_tune_feedback",
    POST_TUNE_FEEDBACK_PATH,
)
post_tune_feedback = importlib.util.module_from_spec(post_tune_feedback_spec)
assert post_tune_feedback_spec is not None and post_tune_feedback_spec.loader is not None
post_tune_feedback_spec.loader.exec_module(post_tune_feedback)

market_regime_spec = importlib.util.spec_from_file_location(
    "quant_paper50_market_regime",
    MARKET_REGIME_PATH,
)
market_regime = importlib.util.module_from_spec(market_regime_spec)
assert market_regime_spec is not None and market_regime_spec.loader is not None
market_regime_spec.loader.exec_module(market_regime)

promotion_checklist_spec = importlib.util.spec_from_file_location(
    "quant_paper50_promotion_checklist",
    PROMOTION_CHECKLIST_PATH,
)
promotion_checklist = importlib.util.module_from_spec(promotion_checklist_spec)
assert promotion_checklist_spec is not None and promotion_checklist_spec.loader is not None
promotion_checklist_spec.loader.exec_module(promotion_checklist)

major_5m_research_spec = importlib.util.spec_from_file_location(
    "quant_major_5m_leverage_research",
    MAJOR_5M_RESEARCH_PATH,
)
major_5m_research = importlib.util.module_from_spec(major_5m_research_spec)
assert major_5m_research_spec is not None and major_5m_research_spec.loader is not None
major_5m_research_spec.loader.exec_module(major_5m_research)

forced_pilot_spec = importlib.util.spec_from_file_location(
    "quant_paper50_forced_pilot",
    FORCED_PILOT_PATH,
)
forced_pilot = importlib.util.module_from_spec(forced_pilot_spec)
assert forced_pilot_spec is not None and forced_pilot_spec.loader is not None
forced_pilot_spec.loader.exec_module(forced_pilot)

parallel_research_spec = importlib.util.spec_from_file_location(
    "quant_paper50_parallel_research",
    PARALLEL_RESEARCH_PATH,
)
parallel_research = importlib.util.module_from_spec(parallel_research_spec)
assert parallel_research_spec is not None and parallel_research_spec.loader is not None
parallel_research_spec.loader.exec_module(parallel_research)

sample_booster_spec = importlib.util.spec_from_file_location(
    "quant_paper50_sample_booster",
    SAMPLE_BOOSTER_PATH,
)
sample_booster = importlib.util.module_from_spec(sample_booster_spec)
assert sample_booster_spec is not None and sample_booster_spec.loader is not None
sample_booster_spec.loader.exec_module(sample_booster)


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

    def test_counterfactual_summarizes_long_and_short_directions(self) -> None:
        payload = counterfactual._summarize(
            [
                {
                    "symbol": "ETHUSDT",
                    "direction": "short",
                    "label": "possible_missed_entry",
                    "net_after_cost_bps": 12.0,
                },
                {
                    "symbol": "PEPEUSDT",
                    "direction": "long",
                    "label": "confirmed_block",
                    "net_after_cost_bps": -8.0,
                },
            ],
            symbols=("ETHUSDT", "PEPEUSDT"),
        )

        self.assertEqual(payload["side_summaries"]["short"]["possible_missed_entry_count"], 1)
        self.assertEqual(payload["side_summaries"]["long"]["label_counts"], {"confirmed_block": 1})

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

    def test_side_scorecard_reports_no_long_failure_to_short_fallback(self) -> None:
        payload = side_scorecard.build_scorecard(
            decisions=[
                {
                    "symbol": "ETHUSDT",
                    "trend_direction": -1,
                    "final_mode": "cash",
                    "side": "flat",
                    "rejection_reasons": ["SCORE_TOO_LOW"],
                },
                {
                    "symbol": "PEPEUSDT",
                    "trend_direction": 1,
                    "final_mode": "futures",
                    "side": "long",
                    "order_intent_notional_usd": 100,
                },
            ],
            counterfactual={
                "side_summaries": {
                    "short": {
                        "decision_count": 10,
                        "possible_missed_entry_count": 2,
                        "label_counts": {"possible_missed_entry": 2},
                    },
                    "long": {
                        "decision_count": 10,
                        "possible_missed_entry_count": 0,
                        "label_counts": {"confirmed_block": 10},
                    },
                }
            },
            futures_outcomes={
                "entries": [
                    {
                        "symbol": "PEPEUSDT",
                        "side": "long",
                        "is_executable": True,
                        "forward_net_returns_bps": {"net_ret15_bps": -5.0},
                    }
                ]
            },
        )

        self.assertFalse(payload["fallback_semantics"]["long_failure_enters_short"])
        self.assertEqual(payload["sides"]["short"]["recommendation"], "test_one_step_short_relaxation_in_paper_only")
        self.assertEqual(payload["sides"]["long"]["recommendation"], "hold_long_gates_accepted_signal_lost")

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

    def test_promotion_checklist_halts_when_order_side_effects_exist(self) -> None:
        payload = promotion_checklist.build_checklist(
            monitor_status={
                "heartbeats": {"live_orders": 1, "tested_orders": 0, "decisions": 10},
                "bitget": {"positions": []},
            },
            external_alpha={},
            overlay_report={},
            side_scorecard={},
            filter_guard_state={},
            filter_guard_latest={},
        )

        self.assertEqual(payload["overall_action"], "halt_review")
        self.assertEqual(payload["candidates"][0]["action"], "halt_review")
        self.assertIn("live_orders_present", payload["candidates"][0]["blockers"])

    def test_post_tune_feedback_flags_bad_post_apply_entries_for_rollback(self) -> None:
        payload = post_tune_feedback.build_feedback(
            state={
                "last_applied_at": "2026-04-25T00:00:00+00:00",
                "window_keys": {"PEPEUSDT": "window"},
                "rollback_profiles": {"PEPEUSDT": {"min_volume_confirmation": 0.56}},
            },
            audit_rows=[
                {
                    "apply_requested": True,
                    "generated_at": "2026-04-25T00:00:00+00:00",
                    "changes": {"PEPEUSDT": {"min_volume_confirmation": 0.54}},
                    "evidence": {"PEPEUSDT": {"entries": [{"direction": "long"}]}},
                }
            ],
            futures_outcomes={
                "entries": [
                    {
                        "timestamp": "2026-04-25T00:20:00+00:00",
                        "symbol": "PEPEUSDT",
                        "side": "long",
                        "is_executable": True,
                        "forward_net_returns_bps": {"net_ret15_bps": -5.0},
                    },
                    {
                        "timestamp": "2026-04-25T00:25:00+00:00",
                        "symbol": "PEPEUSDT",
                        "side": "long",
                        "is_executable": True,
                        "forward_net_returns_bps": {"net_ret15_bps": -8.0},
                    },
                    {
                        "timestamp": "2026-04-25T00:30:00+00:00",
                        "symbol": "PEPEUSDT",
                        "side": "long",
                        "is_executable": True,
                        "forward_net_returns_bps": {"net_ret15_bps": 1.0},
                    },
                ]
            },
            counterfactual={},
            filters={"symbol_filter_profiles": {"PEPEUSDT": {"min_volume_confirmation": 0.54}}},
        )

        self.assertEqual(payload["overall_action"], "review_rollback_candidate")
        self.assertEqual(payload["candidates"][0]["action"], "rollback_candidate")
        self.assertEqual(payload["candidates"][0]["blockers"], [])

    def test_post_tune_feedback_keeps_good_post_apply_entries(self) -> None:
        payload = post_tune_feedback.build_feedback(
            state={
                "last_applied_at": "2026-04-25T00:00:00+00:00",
                "window_keys": {"PEPEUSDT": "window"},
            },
            audit_rows=[
                {
                    "apply_requested": True,
                    "generated_at": "2026-04-25T00:00:00+00:00",
                    "changes": {"PEPEUSDT": {"min_volume_confirmation": 0.54}},
                    "evidence": {"PEPEUSDT": {"entries": [{"direction": "long"}]}},
                }
            ],
            futures_outcomes={
                "entries": [
                    {
                        "timestamp": f"2026-04-25T00:2{idx}:00+00:00",
                        "symbol": "PEPEUSDT",
                        "side": "long",
                        "is_executable": True,
                        "forward_net_returns_bps": {"net_ret15_bps": value},
                    }
                    for idx, value in enumerate([5.0, 6.0, -2.0, 7.0, 8.0])
                ]
            },
            counterfactual={},
            filters={"symbol_filter_profiles": {"PEPEUSDT": {"min_volume_confirmation": 0.54}}},
        )

        self.assertEqual(payload["overall_action"], "keep_current_tune")
        self.assertEqual(payload["candidates"][0]["action"], "keep_tune")

    def test_post_tune_feedback_uses_symbol_specific_apply_time(self) -> None:
        payload = post_tune_feedback.build_feedback(
            state={
                "last_applied_at": "2026-04-25T02:00:00+00:00",
                "window_keys": {"PEPEUSDT": "pepe-window", "DOGEUSDT": "doge-window"},
            },
            audit_rows=[
                {
                    "apply_requested": True,
                    "generated_at": "2026-04-25T00:00:00+00:00",
                    "changes": {"PEPEUSDT": {"min_volume_confirmation": 0.54}},
                    "evidence": {"PEPEUSDT": {"entries": [{"direction": "long"}]}},
                },
                {
                    "apply_requested": True,
                    "generated_at": "2026-04-25T02:00:00+00:00",
                    "changes": {"DOGEUSDT": {"min_edge_to_cost": 2.55}},
                    "evidence": {"DOGEUSDT": {"entries": [{"direction": "long"}]}},
                },
            ],
            futures_outcomes={
                "entries": [
                    {
                        "timestamp": "2026-04-25T01:00:00+00:00",
                        "symbol": "PEPEUSDT",
                        "side": "long",
                        "is_executable": True,
                        "forward_net_returns_bps": {"net_ret15_bps": 3.0},
                    },
                    {
                        "timestamp": "2026-04-25T01:00:00+00:00",
                        "symbol": "DOGEUSDT",
                        "side": "long",
                        "is_executable": True,
                        "forward_net_returns_bps": {"net_ret15_bps": 9.0},
                    },
                ]
            },
            counterfactual={},
            filters={"symbol_filter_profiles": {"PEPEUSDT": {}, "DOGEUSDT": {}}},
        )

        reports = payload["symbol_reports"]
        self.assertEqual(
            reports["PEPEUSDT"]["metrics"]["executable_post_tune_entries"]["net_return_count"],
            1,
        )
        self.assertEqual(
            reports["DOGEUSDT"]["metrics"]["executable_post_tune_entries"]["net_return_count"],
            0,
        )
        self.assertEqual(reports["PEPEUSDT"]["metrics"]["applied_at"], "2026-04-25T00:00:00+00:00")
        self.assertEqual(reports["DOGEUSDT"]["metrics"]["applied_at"], "2026-04-25T02:00:00+00:00")

    def test_promotion_checklist_surfaces_post_tune_rollback_candidate(self) -> None:
        payload = promotion_checklist.build_checklist(
            monitor_status={
                "heartbeats": {"live_orders": 0, "tested_orders": 0, "decisions": 10},
                "bitget": {"positions": []},
            },
            external_alpha={},
            overlay_report={},
            side_scorecard={},
            filter_guard_state={},
            filter_guard_latest={},
            post_tune_feedback={
                "candidates": [
                    {
                        "id": "post_tune_feedback:PEPEUSDT",
                        "scope": "symbol_filter",
                        "symbol": "PEPEUSDT",
                        "side": "long",
                        "action": "rollback_candidate",
                        "reason": "Bad post-tune entries.",
                        "metrics": {"executable_post_tune_entries": {"net_return_count": 3}},
                        "blockers": [],
                        "next_step": "restore_previous_symbol_profile_or_tighten_one_step",
                    }
                ]
            },
        )

        self.assertEqual(payload["overall_action"], "review_rollback_candidate")
        self.assertEqual(payload["candidates"][0]["source"], "paper50_post_tune_feedback")

    def test_promotion_checklist_keeps_new_filter_guard_candidate_after_prior_apply(self) -> None:
        payload = promotion_checklist.build_checklist(
            monitor_status={
                "heartbeats": {"live_orders": 0, "tested_orders": 0, "decisions": 10},
                "bitget": {"positions": []},
            },
            external_alpha={},
            overlay_report={},
            side_scorecard={},
            filter_guard_state={
                "last_applied_at": "2026-04-25T00:00:00+00:00",
                "window_keys": {"PEPEUSDT": "old-window"},
            },
            filter_guard_latest={
                "changes": {"DOGEUSDT": {"min_edge_to_cost": 2.55}},
                "evidence": {"DOGEUSDT": {"quality_missed_count": 2}},
            },
        )

        actions_by_id = {row["id"]: row["action"] for row in payload["candidates"]}
        self.assertEqual(actions_by_id["filter_guard:PEPEUSDT"], "post_tune_watch")
        self.assertEqual(actions_by_id["filter_guard:DOGEUSDT"], "paper_tune_candidate")
        self.assertEqual(payload["overall_action"], "review_paper_candidate")

    def test_promotion_checklist_uses_symbol_specific_filter_guard_apply_time(self) -> None:
        payload = promotion_checklist.build_checklist(
            monitor_status={
                "heartbeats": {"live_orders": 0, "tested_orders": 0, "decisions": 10},
                "bitget": {"positions": []},
            },
            external_alpha={},
            overlay_report={},
            side_scorecard={},
            filter_guard_state={
                "last_applied_at": "2026-04-25T02:00:00+00:00",
                "window_keys": {"PEPEUSDT": "pepe-window", "DOGEUSDT": "doge-window"},
            },
            filter_guard_latest={},
            filter_guard_audit_rows=[
                {
                    "apply_requested": True,
                    "generated_at": "2026-04-25T00:00:00+00:00",
                    "changes": {"PEPEUSDT": {"min_volume_confirmation": 0.54}},
                    "evidence": {"PEPEUSDT": {"entries": [{"direction": "long"}]}},
                },
                {
                    "apply_requested": True,
                    "generated_at": "2026-04-25T02:00:00+00:00",
                    "changes": {"DOGEUSDT": {"min_edge_to_cost": 2.55}},
                    "evidence": {"DOGEUSDT": {"entries": [{"direction": "long"}]}},
                },
            ],
        )

        metrics_by_id = {
            row["id"]: row["metrics"]
            for row in payload["candidates"]
            if row["id"].startswith("filter_guard:")
        }
        self.assertEqual(metrics_by_id["filter_guard:PEPEUSDT"]["last_applied_at"], "2026-04-25T00:00:00+00:00")
        self.assertEqual(metrics_by_id["filter_guard:DOGEUSDT"]["last_applied_at"], "2026-04-25T02:00:00+00:00")

    def test_market_regime_allows_alt_long_when_alts_outperform_core(self) -> None:
        payload = market_regime.build_regime(
            [
                {"symbol": "BTCUSDT", "priceChangePercent": "-0.4", "lastPrice": "100", "quoteVolume": "1", "count": 10},
                {"symbol": "ETHUSDT", "priceChangePercent": "0.1", "lastPrice": "100", "quoteVolume": "1", "count": 10},
                {"symbol": "DOGEUSDT", "priceChangePercent": "0.6", "lastPrice": "1", "quoteVolume": "1", "count": 10},
                {"symbol": "SOLUSDT", "priceChangePercent": "1.2", "lastPrice": "1", "quoteVolume": "1", "count": 10},
                {"symbol": "1000PEPEUSDT", "priceChangePercent": "0.7", "lastPrice": "1", "quoteVolume": "1", "count": 10},
                {"symbol": "XRPUSDT", "priceChangePercent": "-0.1", "lastPrice": "1", "quoteVolume": "1", "count": 10},
            ]
        )

        self.assertEqual(payload["posture"], "alt_relative_long_ok")
        self.assertTrue(payload["symbol_gates"]["DOGEUSDT"]["long_relax_allowed"])
        self.assertTrue(payload["symbol_gates"]["PEPEUSDT"]["long_relax_allowed"])

    def test_market_regime_blocks_alt_long_in_broad_risk_off(self) -> None:
        payload = market_regime.build_regime(
            [
                {"symbol": "BTCUSDT", "priceChangePercent": "-2.0"},
                {"symbol": "ETHUSDT", "priceChangePercent": "-1.4"},
                {"symbol": "DOGEUSDT", "priceChangePercent": "-0.8"},
                {"symbol": "SOLUSDT", "priceChangePercent": "-0.7"},
            ]
        )

        self.assertEqual(payload["posture"], "broad_risk_off")
        self.assertFalse(payload["symbol_gates"]["DOGEUSDT"]["long_relax_allowed"])

    def test_promotion_checklist_market_regime_can_block_filter_candidate(self) -> None:
        payload = promotion_checklist.build_checklist(
            monitor_status={
                "heartbeats": {"live_orders": 0, "tested_orders": 0, "decisions": 10},
                "bitget": {"positions": []},
            },
            external_alpha={},
            overlay_report={},
            side_scorecard={},
            filter_guard_state={},
            filter_guard_latest={
                "changes": {"DOGEUSDT": {"min_edge_to_cost": 2.55}},
                "evidence": {"DOGEUSDT": {"quality_missed_count": 2}},
            },
            market_regime={
                "posture": "broad_risk_off",
                "symbol_gates": {"DOGEUSDT": {"long_relax_allowed": False}},
            },
        )

        candidate = [row for row in payload["candidates"] if row["id"] == "filter_guard:DOGEUSDT"][0]
        self.assertEqual(candidate["action"], "watch_only")
        self.assertIn("market_regime_blocks_long_relaxation", candidate["blockers"])

    def test_promotion_checklist_keeps_shadow_watch_report_only(self) -> None:
        payload = promotion_checklist.build_checklist(
            monitor_status={
                "heartbeats": {"live_orders": 0, "tested_orders": 0, "decisions": 10},
                "bitget": {"positions": []},
            },
            external_alpha={},
            overlay_report={
                "leg_stats": [
                    {
                        "key": "SOLUSDT|crowded_long_unwind|short",
                        "symbol": "SOLUSDT",
                        "strategy": "crowded_long_unwind",
                        "side": "short",
                        "matched_count": 9,
                        "avg_ret15_bps": 0.832249,
                        "win15_rate": 0.555556,
                        "worst_ret15_bps": -12.766204,
                        "latest_ret15_bps": -3.015542,
                        "verdict": "shadow_watch",
                    }
                ]
            },
            side_scorecard={},
            filter_guard_state={},
            filter_guard_latest={},
        )

        overlay = [
            row
            for row in payload["candidates"]
            if row["id"] == "long_failure_short_overlay:SOLUSDT|crowded_long_unwind|short"
        ][0]
        self.assertEqual(overlay["action"], "watch_only")
        self.assertIn("verdict_shadow_watch", overlay["blockers"])
        self.assertIn("worst_ret15_lte_-10bps", overlay["blockers"])

    def test_promotion_checklist_promotes_only_strong_paper_overlay(self) -> None:
        payload = promotion_checklist.build_checklist(
            monitor_status={
                "heartbeats": {"live_orders": 0, "tested_orders": 0, "decisions": 10},
                "bitget": {"positions": []},
            },
            external_alpha={},
            overlay_report={
                "leg_stats": [
                    {
                        "key": "BTCUSDT|oi_exhaustion_reversion|short",
                        "symbol": "BTCUSDT",
                        "strategy": "oi_exhaustion_reversion",
                        "side": "short",
                        "matched_count": 14,
                        "avg_ret15_bps": 6.5,
                        "win15_rate": 0.714286,
                        "worst_ret15_bps": -8.0,
                        "latest_ret15_bps": 3.0,
                        "verdict": "paper_short_overlay_watch",
                    }
                ]
            },
            side_scorecard={},
            filter_guard_state={},
            filter_guard_latest={},
        )

        self.assertEqual(payload["overall_action"], "review_paper_candidate")
        overlay = [
            row
            for row in payload["candidates"]
            if row["id"] == "long_failure_short_overlay:BTCUSDT|oi_exhaustion_reversion|short"
        ][0]
        self.assertEqual(overlay["action"], "paper_candidate")
        self.assertEqual(overlay["blockers"], [])

    def test_promotion_checklist_surfaces_forced_pilot_watch_state(self) -> None:
        payload = promotion_checklist.build_checklist(
            monitor_status={
                "heartbeats": {"live_orders": 0, "tested_orders": 0, "decisions": 10},
                "bitget": {"positions": []},
            },
            external_alpha={},
            overlay_report={},
            side_scorecard={},
            filter_guard_state={},
            filter_guard_latest={},
            forced_pilot={
                "active_pilots": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "long",
                        "matured_horizons": [5, 10, 15],
                        "evaluation": {
                            "label": "confirmed_block",
                            "net_after_cost_bps": -10.0,
                        },
                    }
                ],
                "completed_recent": [],
                "summary": {
                    "action": "collect_forced_pilot_outcomes",
                    "completed_count": 0,
                    "net_return_count": 0,
                },
            },
        )

        forced = [row for row in payload["candidates"] if row["id"] == "forced_pilot:block_override_quality"][0]
        self.assertEqual(forced["action"], "watch_only")
        self.assertEqual(forced["metrics"]["active_symbol"], "BTCUSDT")
        self.assertEqual(forced["metrics"]["active_net_after_cost_bps"], -10.0)

    def test_major_5m_research_finds_major_trend_profiles(self) -> None:
        bars = []
        price = 100.0
        for idx in range(360):
            if idx < 50:
                price *= 1.0001
            elif idx < 260:
                price *= 1.0014
            else:
                price *= 1.0006
            bars.append(
                {
                    "open_time": idx * 300000,
                    "close_time": idx * 300000 + 299999,
                    "open": price / 1.0006,
                    "high": price * 1.001,
                    "low": price * 0.9995,
                    "close": price,
                    "quote_volume": 1000.0 if idx < 50 else 1000.0 + (idx * 35.0),
                }
            )

        payload = major_5m_research.build_report({"BTCUSDT": bars}, cost_bps=1.0)

        self.assertGreater(payload["signal_counts"]["BTCUSDT"], 0)
        self.assertEqual(payload["overall_action"], "test_major_5m_overlay_paper_only")
        self.assertTrue(any(row["decision"] == "paper_watch" for row in payload["top_profiles"]))

    def test_major_5m_research_flags_sample_too_small(self) -> None:
        payload = major_5m_research.build_report({"BTCUSDT": []})

        self.assertEqual(payload["overall_action"], "insufficient_data")
        self.assertEqual(payload["errors"]["BTCUSDT"], "insufficient_5m_bars")

    def test_forced_pilot_opens_blocked_futures_candidate_without_order_side_effects(self) -> None:
        rows = [
            {
                "decision_id": "weak",
                "symbol": "BTCUSDT",
                "timestamp": "2026-04-25T00:00:00+00:00",
                "candidate_mode": "futures",
                "final_mode": "cash",
                "rejected": True,
                "reference_price": 65000.0,
                "net_expected_edge_bps": 2.0,
                "estimated_round_trip_cost_bps": 8.0,
                "predictability_score": 62.0,
                "trend_direction": 1,
            },
            {
                "decision_id": "strong",
                "symbol": "ETHUSDT",
                "timestamp": "2026-04-25T00:05:00+00:00",
                "candidate_mode": "futures",
                "final_mode": "cash",
                "rejected": True,
                "reference_price": 3200.0,
                "net_expected_edge_bps": 48.0,
                "estimated_round_trip_cost_bps": 8.0,
                "predictability_score": 82.0,
                "trend_direction": -1,
                "volume_confirmation": 0.7,
                "liquidity_score": 0.9,
                "rejection_reasons": ["SYMBOL_PROFILE_EXPECTED_PROFIT_TOO_SMALL"],
            },
        ]

        next_state, payload = forced_pilot.build_forced_pilot(
            rows=rows,
            state={},
            client=object(),
            open_new=True,
            max_active=1,
            lookback=10,
        )

        self.assertTrue(payload["paper_only"])
        self.assertTrue(payload["no_order_side_effects"])
        self.assertEqual(payload["opened_pilot"]["pilot_id"], "strong")
        self.assertEqual(payload["opened_pilot"]["side"], "short")
        self.assertEqual(len(next_state["active_pilots"]), 1)

    def test_forced_pilot_rejects_after_three_negative_completed_pilots(self) -> None:
        completed = [
            {
                "estimated_round_trip_cost_bps": 2.0,
                "evaluation": {"forward_returns_bps": {"ret30_bps": -4.0}},
            },
            {
                "estimated_round_trip_cost_bps": 2.0,
                "evaluation": {"forward_returns_bps": {"ret30_bps": -8.0}},
            },
            {
                "estimated_round_trip_cost_bps": 2.0,
                "evaluation": {"forward_returns_bps": {"ret30_bps": 1.0}},
            },
        ]

        summary = forced_pilot._summarize(completed)

        self.assertEqual(summary["completed_count"], 3)
        self.assertEqual(summary["net_return_count"], 3)
        self.assertEqual(summary["action"], "forced_pilot_reject_or_tighten")

    def test_parallel_research_summary_ranks_paper_only_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            decision_root = base / "paper50"
            alpha_dir = decision_root / "bitget_external_alpha_shadow"
            output_dir = decision_root / "artifacts" / "parallel_research"
            (decision_root / "artifacts").mkdir(parents=True)
            alpha_dir.mkdir(parents=True)
            (alpha_dir / "status.json").write_text(
                json.dumps(
                    {
                        "best_mature_candidates": [
                            {
                                "key": "PEPEUSDT|oi_exhaustion_reversion|short",
                                "avg_ret15_bps": 12.0,
                                "win15_rate": 1.0,
                                "count": 3,
                                "latest_ret15_bps": 10.0,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (output_dir / "external_alpha_combo").mkdir(parents=True)
            (output_dir / "external_alpha_combo" / "external_alpha_combo_ranking.json").write_text(
                json.dumps(
                    {
                        "best_combo": {
                            "name": "core",
                            "status": "watch",
                            "avg_leg_ret15_bps": 20.0,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (decision_root / "_monitor_status.json").write_text(
                json.dumps({"heartbeats": {"live_orders": 0, "tested_orders": 0, "decisions": 5}, "bitget": {"positions": []}}),
                encoding="utf-8",
            )

            payload = parallel_research.build_summary(
                decision_root=decision_root,
                alpha_dir=alpha_dir,
                output_dir=output_dir,
                commands=[{"name": "ok", "returncode": 0}],
            )

        self.assertTrue(payload["paper_only"])
        self.assertTrue(payload["no_order_side_effects"])
        self.assertEqual(payload["overall_action"], "continue_parallel_observation")
        self.assertEqual(payload["top_candidates"][0]["id"], "combo:core")

    def test_sample_booster_promotes_only_after_target_sample_and_quality_gate(self) -> None:
        weak = {
            "PEPEUSDT|oi_exhaustion_reversion|short": {
                "count": 11,
                "avg_ret15_bps": 20.0,
                "win15_rate": 1.0,
                "worst_ret15_bps": 10.0,
            }
        }
        strong = {
            "PEPEUSDT|oi_exhaustion_reversion|short": {
                "count": 12,
                "avg_ret15_bps": 20.0,
                "win15_rate": 0.75,
                "worst_ret15_bps": -5.0,
            }
        }

        self.assertEqual(sample_booster._next_action(weak, target_sample=12), "collect_more_samples")
        self.assertEqual(sample_booster._next_action(strong, target_sample=12), "review_paper_candidate")

    def test_fetch_klines_cached_retries_then_succeeds(self) -> None:
        attempts: list[int] = []

        def flaky_fetcher(**_kwargs: object) -> list[dict[str, object]]:
            attempts.append(1)
            if len(attempts) < 3:
                raise ConnectionError("dns failure")
            return [{"open_time": 1_000, "close_price": 100.0}]

        with tempfile.TemporaryDirectory() as tmp:
            bars = counterfactual.fetch_klines_cached(
                flaky_fetcher,
                symbol="BTCUSDT",
                start_ms=1_000,
                end_ms=2_000,
                forward_minutes=15,
                cache_dir=Path(tmp),
                sleep_fn=lambda _: None,
            )
            self.assertEqual(len(attempts), 3)
            self.assertEqual(bars[0]["close_price"], 100.0)
            cached = json.loads((Path(tmp) / "BTCUSDT_1000_2000.json").read_text())
            self.assertEqual(cached, bars)

    def test_fetch_klines_cached_returns_cache_without_calling_fetcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            cache_dir.mkdir(exist_ok=True)
            (cache_dir / "ETHUSDT_500_1500.json").write_text(
                json.dumps([{"open_time": 500, "close_price": 42.0}])
            )

            def must_not_be_called(**_kwargs: object) -> list[dict[str, object]]:
                raise AssertionError("fetcher should not be called on cache hit")

            bars = counterfactual.fetch_klines_cached(
                must_not_be_called,
                symbol="ETHUSDT",
                start_ms=500,
                end_ms=1_500,
                forward_minutes=15,
                cache_dir=cache_dir,
                sleep_fn=lambda _: None,
            )
            self.assertEqual(bars[0]["close_price"], 42.0)

    def test_fetch_klines_cached_raises_after_max_retries(self) -> None:
        def always_fails(**_kwargs: object) -> list[dict[str, object]]:
            raise ConnectionError("dns")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                counterfactual.fetch_klines_cached(
                    always_fails,
                    symbol="DOGEUSDT",
                    start_ms=0,
                    end_ms=1,
                    forward_minutes=15,
                    cache_dir=Path(tmp),
                    max_retries=2,
                    sleep_fn=lambda _: None,
                )

    def test_decompose_costs_uses_calibration_when_available(self) -> None:
        from quant_binance.cost_calibration import CostCalibration, SymbolCostCalibration

        calibration = CostCalibration(
            generated_at="2026-04-25T00:00:00+00:00",
            lookback_hours=72,
            global_empirical_fee_bps=4.0,
            global_empirical_entry_slippage_bps=2.0,
            global_empirical_exit_slippage_bps=2.0,
            slippage_untrusted=True,
            symbol_calibrations=(
                SymbolCostCalibration(
                    symbol="DOGEUSDT",
                    empirical_fee_bps=5.0,
                    empirical_entry_slippage_bps=1.5,
                    empirical_exit_slippage_bps=1.5,
                    fee_sample_count=200,
                    slippage_sample_count=200,
                    slippage_untrusted=False,
                ),
            ),
        )
        breakdown = counterfactual._decompose_costs(
            symbol="DOGEUSDT",
            direction="short",
            upstream_cost_bps=12.0,
            calibration=calibration,
            forward_minutes=15,
            funding_rate_8h=0.0001,
        )
        self.assertEqual(breakdown["entry_fee_bps"], 5.0)
        self.assertEqual(breakdown["exit_fee_bps"], 5.0)
        self.assertEqual(breakdown["entry_slippage_bps"], 1.5)
        self.assertEqual(breakdown["exit_slippage_bps"], 1.5)
        # Short with positive funding rate => receives funding => negative bps
        self.assertLess(breakdown["funding_bps"], 0.0)
        self.assertFalse(breakdown["slippage_untrusted"])
        self.assertEqual(breakdown["source"], "calibration")

    def test_decompose_costs_falls_back_when_no_calibration(self) -> None:
        breakdown = counterfactual._decompose_costs(
            symbol="BTCUSDT",
            direction="long",
            upstream_cost_bps=12.0,
            calibration=None,
            forward_minutes=15,
        )
        self.assertEqual(breakdown["entry_fee_bps"], 6.0)
        self.assertEqual(breakdown["exit_fee_bps"], 6.0)
        self.assertEqual(breakdown["entry_slippage_bps"], 0.0)
        self.assertTrue(breakdown["slippage_untrusted"])
        self.assertEqual(breakdown["source"], "fallback_no_calibration")

    def test_decompose_costs_reconciliation_diff_tracks_drift(self) -> None:
        from quant_binance.cost_calibration import CostCalibration, SymbolCostCalibration

        calibration = CostCalibration(
            generated_at="2026-04-25T00:00:00+00:00",
            lookback_hours=72,
            global_empirical_fee_bps=4.0,
            global_empirical_entry_slippage_bps=2.0,
            global_empirical_exit_slippage_bps=2.0,
            slippage_untrusted=False,
            symbol_calibrations=(
                SymbolCostCalibration(
                    symbol="ETHUSDT",
                    empirical_fee_bps=4.0,
                    empirical_entry_slippage_bps=2.0,
                    empirical_exit_slippage_bps=2.0,
                    fee_sample_count=200,
                    slippage_sample_count=200,
                    slippage_untrusted=False,
                ),
            ),
        )
        breakdown = counterfactual._decompose_costs(
            symbol="ETHUSDT",
            direction="long",
            upstream_cost_bps=20.0,
            calibration=calibration,
            forward_minutes=15,
            funding_rate_8h=0.0001,
        )
        # 4+4+2+2 + (positive funding for long) = 12 + tiny funding ~= 12.03
        # upstream is 20 -> diff ~= -7.97 means upstream is more conservative
        self.assertLess(breakdown["reconciliation_diff_bps"], 0.0)
        self.assertGreater(breakdown["total_modeled_bps"], 11.9)
        self.assertLess(breakdown["total_modeled_bps"], 12.1)

    def test_compute_slippage_stress_marks_unsurvivable_at_10bps(self) -> None:
        breakdown = {
            "entry_fee_bps": 5.0,
            "exit_fee_bps": 5.0,
            "funding_bps": 0.0,
        }
        # forward_ret 15bps, fees 10bps total => base_net 5bps. At 10bps stress
        # (20bps total slippage cost) => net = -15bps => unsurvivable.
        stress = counterfactual._compute_slippage_stress(
            forward_ret_bps=15.0,
            breakdown=breakdown,
        )
        self.assertTrue(stress["available"])
        self.assertEqual(stress["base_net_bps"], 5.0)
        self.assertEqual(stress["net_at_0bps"], 5.0)
        self.assertEqual(stress["net_at_10bps"], -15.0)
        self.assertTrue(stress["cost_unsurvivable"])

    def test_compute_slippage_stress_survives_when_edge_large(self) -> None:
        breakdown = {
            "entry_fee_bps": 2.0,
            "exit_fee_bps": 2.0,
            "funding_bps": 0.0,
        }
        # forward_ret 50bps, fees 4bps => base 46. At 10bps stress => net = 26.
        stress = counterfactual._compute_slippage_stress(
            forward_ret_bps=50.0,
            breakdown=breakdown,
        )
        self.assertTrue(stress["available"])
        self.assertEqual(stress["net_at_10bps"], 26.0)
        self.assertFalse(stress["cost_unsurvivable"])

    def test_compute_slippage_stress_handles_missing_forward_ret(self) -> None:
        stress = counterfactual._compute_slippage_stress(
            forward_ret_bps=None,
            breakdown={"entry_fee_bps": 2.0, "exit_fee_bps": 2.0, "funding_bps": 0.0},
        )
        self.assertFalse(stress["available"])
        self.assertFalse(stress["cost_unsurvivable"])


if __name__ == "__main__":
    unittest.main()
