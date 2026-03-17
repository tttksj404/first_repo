from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from quant_binance.performance_report import build_runtime_performance_report


@dataclass(frozen=True)
class ValidationCriteriaRow:
    category: str
    rule: str
    action: str


@dataclass(frozen=True)
class WeeklyValidationReport:
    base_dir: str
    generated_at: str
    lookback_days: int
    run_count: int
    period_start: str
    period_end: str
    total_closed_trade_count: int
    total_realized_pnl_usd: float
    total_live_order_count: int
    total_tested_order_count: int
    symbol_summary: tuple[dict[str, object], ...]
    regime_summary: tuple[dict[str, object], ...]
    criteria: tuple[ValidationCriteriaRow, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "base_dir": self.base_dir,
            "generated_at": self.generated_at,
            "lookback_days": self.lookback_days,
            "run_count": self.run_count,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "total_closed_trade_count": self.total_closed_trade_count,
            "total_realized_pnl_usd": self.total_realized_pnl_usd,
            "total_live_order_count": self.total_live_order_count,
            "total_tested_order_count": self.total_tested_order_count,
            "symbol_summary": list(self.symbol_summary),
            "regime_summary": list(self.regime_summary),
            "criteria": [asdict(item) for item in self.criteria],
        }


def _criteria_table() -> tuple[ValidationCriteriaRow, ...]:
    return (
        ValidationCriteriaRow(
            category="prune",
            rule="trade_count >= 3 and expectancy_usd < 0, or repeated thin-edge/liquidity rejections without positive edge",
            action="universe에서 제거 또는 priority 해제",
        ),
        ValidationCriteriaRow(
            category="observe_only",
            rule="cash_count가 높고 LIQUIDITY_TOO_WEAK/EDGE_TOO_THIN 반복, 하지만 trade_count 표본이 부족함",
            action="매매 제외, 관찰만 유지",
        ),
        ValidationCriteriaRow(
            category="keep",
            rule="expectancy_usd >= 0 또는 표본 부족이지만 평균 edge가 양수",
            action="현재 유니버스 유지",
        ),
        ValidationCriteriaRow(
            category="promote",
            rule="trade_count >= 3, expectancy_usd > 0, avg_net_edge_bps > 0, rejection pressure 낮음",
            action="priority_symbols 후보로 승격 검토",
        ),
    )


def _resolve_recent_runs(*, base_dir: Path, lookback_days: int) -> list[Path]:
    mode_root = base_dir / "output" / "paper-live-shell"
    if not mode_root.exists():
        return []
    now = datetime.now(UTC)
    threshold = now - timedelta(days=lookback_days)
    runs: list[Path] = []
    for candidate in mode_root.iterdir():
        if not candidate.is_dir() or candidate.name == "latest":
            continue
        modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
        if modified >= threshold:
            runs.append(candidate)
    runs.sort(key=lambda p: p.stat().st_mtime)
    return runs


def _load_summary(run_dir: Path) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        return {}
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    cumulative = 0.0
    max_drawdown = 0.0
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return round(max_drawdown, 6)


def _weighted_metric(numerator: float, denominator: float) -> float:
    if denominator <= 0.0:
        return 0.0
    return round(numerator / denominator, 6)


def _safe_ratio(numerator: Any, denominator: Any) -> float:
    denom = _safe_float(denominator)
    if denom <= 0.0:
        return 0.0
    return round(_safe_float(numerator) / denom, 6)


def _run_validation_snapshot(*, run_dir: Path) -> dict[str, object]:
    report = build_runtime_performance_report(run_dir=run_dir)
    summary = _load_summary(run_dir)
    live_order_count = _safe_int(summary.get("live_order_count"))
    accepted_live_order_count = _safe_int(summary.get("accepted_live_order_count"))
    rejected_live_order_count = _safe_int(summary.get("rejected_live_order_count"))
    walk_forward = []
    for row in report.walk_forward:
        walk_forward.append(
            {
                "run_id": run_dir.name,
                "window_index": _safe_int(row.get("window_index")),
                "start": str(row.get("start", "")),
                "end": str(row.get("end", "")),
                "decision_count": _safe_int(row.get("decision_count")),
                "futures_count": _safe_int(row.get("futures_count")),
                "spot_count": _safe_int(row.get("spot_count")),
                "cash_count": _safe_int(row.get("cash_count")),
                "avg_score": round(_safe_float(row.get("avg_score")), 6),
                "avg_net_edge_bps": round(_safe_float(row.get("avg_net_edge_bps")), 6),
            }
        )
    return {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "generated_at": str(summary.get("generated_at", "")),
        "closed_trade_count": report.closed_trade_count,
        "realized_pnl_usd": round(report.realized_pnl_usd, 6),
        "live_order_count": live_order_count,
        "accepted_live_order_count": accepted_live_order_count,
        "rejected_live_order_count": rejected_live_order_count,
        "tested_order_count": _safe_int(summary.get("tested_order_count")),
        "avg_slippage_bps": round(_safe_float(summary.get("avg_slippage_bps")), 6),
        "avg_edge_retention_ratio": round(_safe_float(summary.get("avg_edge_retention_ratio")), 6),
        "avg_realized_edge_bps": round(_safe_float(summary.get("avg_realized_edge_bps")), 6),
        "avg_expected_edge_bps": round(_safe_float(summary.get("avg_expected_edge_bps")), 6),
        "reject_rate": round(rejected_live_order_count / max(live_order_count, 1), 6) if live_order_count > 0 else 0.0,
        "protection_degraded_rate": round(_safe_float(summary.get("protection_degraded_rate")), 6),
        "walk_forward": walk_forward,
        "pruning_recommendations": [dict(item) for item in report.pruning_recommendations],
    }


def _build_micro_live_gate(*, live_order_count: int, rejected_live_order_count: int, avg_slippage_bps: float, avg_realized_edge_bps: float, closed_trade_count: int) -> dict[str, object]:
    available = live_order_count > 0 or closed_trade_count > 0
    minimum_live_order_count = 2
    minimum_closed_trade_count = 1
    if not available:
        return {
            "available": False,
            "status": "not_available",
            "required_live_order_count": minimum_live_order_count,
            "required_closed_trade_count": minimum_closed_trade_count,
            "reason": "NO_MICRO_LIVE_EVIDENCE",
        }
    pass_gate = (
        live_order_count >= minimum_live_order_count
        and closed_trade_count >= minimum_closed_trade_count
        and (rejected_live_order_count / max(live_order_count, 1)) <= 0.2
        and avg_slippage_bps <= 15.0
        and avg_realized_edge_bps > 0.0
    )
    reason = "MICRO_LIVE_THRESHOLD_PASSED" if pass_gate else "MICRO_LIVE_THRESHOLD_NOT_MET"
    return {
        "available": True,
        "status": "pass" if pass_gate else "pending",
        "required_live_order_count": minimum_live_order_count,
        "required_closed_trade_count": minimum_closed_trade_count,
        "live_order_count": live_order_count,
        "closed_trade_count": closed_trade_count,
        "reject_rate": round(rejected_live_order_count / max(live_order_count, 1), 6) if live_order_count > 0 else 0.0,
        "avg_slippage_bps": round(avg_slippage_bps, 6),
        "avg_realized_edge_bps": round(avg_realized_edge_bps, 6),
        "reason": reason,
    }


def _runtime_metric_signal(*, candidate: float | None, current: float | None, higher_is_better: bool, tolerance: float) -> tuple[float, float]:
    if candidate is None or current is None:
        return 0.0, 0.0
    delta = round(candidate - current, 6)
    if abs(delta) <= tolerance:
        return 0.0, delta
    return ((1.0 if delta > 0.0 else -1.0) if higher_is_better else (-1.0 if delta > 0.0 else 1.0)), delta


def _aggregate_pruning_recommendations(
    run_snapshots: list[dict[str, object]],
) -> list[dict[str, object]]:
    severity = {"prune": 0, "demote": 1, "observe_only": 2, "keep": 3}
    merged: dict[str, dict[str, object]] = {}
    for snapshot in run_snapshots:
        for item in list(snapshot.get("pruning_recommendations", []) or []):
            symbol = str(item.get("symbol", "") or "")
            if not symbol:
                continue
            candidate = dict(item)
            existing = merged.get(symbol)
            if existing is None:
                merged[symbol] = candidate
                continue
            existing_rank = severity.get(str(existing.get("recommendation", "keep")), 99)
            candidate_rank = severity.get(str(candidate.get("recommendation", "keep")), 99)
            if candidate_rank < existing_rank:
                merged[symbol] = candidate
                continue
            if candidate_rank == existing_rank:
                existing_decisions = _safe_int(existing.get("decision_count"))
                candidate_decisions = _safe_int(candidate.get("decision_count"))
                if candidate_decisions >= existing_decisions:
                    merged[symbol] = candidate
    return sorted(
        merged.values(),
        key=lambda item: (
            severity.get(str(item.get("recommendation", "keep")), 99),
            str(item.get("symbol", "")),
        ),
    )


def _compare_runtime_evidence(*, candidate_evidence: dict[str, Any], current_evidence: dict[str, Any]) -> dict[str, object]:
    current_present = bool(current_evidence)
    metric_rows = (
        ("runner_total_realized_pnl_usd", True, 0.5),
        ("runner_drawdown_to_pnl_ratio", False, 0.05),
        ("runner_reject_rate", False, 0.01),
        ("runner_avg_slippage_bps", False, 0.5),
        ("runner_avg_realized_edge_bps", True, 0.25),
        ("runner_avg_edge_retention_ratio", True, 0.02),
        ("runner_shadow_alignment_score", True, 0.03),
        ("runner_positive_walk_forward_ratio", True, 0.05),
    )
    metric_deltas: dict[str, float] = {}
    compared_metrics: list[str] = []
    metric_comparisons: list[dict[str, object]] = []
    runtime_score = 0.0
    for metric_name, higher_is_better, tolerance in metric_rows:
        candidate_value = candidate_evidence.get(metric_name)
        current_value = current_evidence.get(metric_name)
        signal, delta = _runtime_metric_signal(
            candidate=_safe_float(candidate_value) if candidate_value is not None else None,
            current=_safe_float(current_value) if current_value is not None else None,
            higher_is_better=higher_is_better,
            tolerance=tolerance,
        )
        if candidate_value is None or current_value is None:
            continue
        compared_metrics.append(metric_name)
        metric_deltas[f"{metric_name}_delta"] = delta
        runtime_score += signal
        metric_comparisons.append(
            {
                "metric": metric_name,
                "candidate_value": round(_safe_float(candidate_value), 6),
                "current_value": round(_safe_float(current_value), 6),
                "delta": delta,
                "verdict": (
                    "candidate_better"
                    if signal > 0.0
                    else ("candidate_worse" if signal < 0.0 else "keep")
                ),
            }
        )
    verdict = "keep"
    if runtime_score >= 1.0:
        verdict = "candidate_better"
    elif runtime_score <= -1.0:
        verdict = "candidate_worse"
    return {
        "runtime_evidence_available": current_present and bool(compared_metrics),
        "runtime_comparison_verdict": verdict,
        "candidate_vs_current_runtime_score": round(runtime_score, 6),
        "compared_metrics": compared_metrics,
        "metric_comparisons": metric_comparisons,
        **metric_deltas,
    }


def build_weekly_validation_report(*, base_dir: str | Path = "quant_runtime", lookback_days: int = 7) -> WeeklyValidationReport:
    root = Path(base_dir)
    runs = _resolve_recent_runs(base_dir=root, lookback_days=lookback_days)
    generated_at = datetime.now(UTC).isoformat()
    if not runs:
        return WeeklyValidationReport(
            base_dir=str(root),
            generated_at=generated_at,
            lookback_days=lookback_days,
            run_count=0,
            period_start="",
            period_end="",
            total_closed_trade_count=0,
            total_realized_pnl_usd=0.0,
            total_live_order_count=0,
            total_tested_order_count=0,
            symbol_summary=(),
            regime_summary=(),
            criteria=_criteria_table(),
        )

    symbol_buckets: dict[str, dict[str, float | int]] = {}
    regime_buckets: dict[str, dict[str, float | int]] = {}
    total_closed_trade_count = 0
    total_realized_pnl = 0.0
    total_live_orders = 0
    total_tested_orders = 0

    for run_dir in runs:
        report = build_runtime_performance_report(run_dir=run_dir)
        summary = _load_summary(run_dir)
        total_closed_trade_count += report.closed_trade_count
        total_realized_pnl += report.realized_pnl_usd
        total_live_orders += int(summary.get("live_order_count") or 0)
        total_tested_orders += int(summary.get("tested_order_count") or 0)

        for row in report.symbol_expectancy:
            bucket = symbol_buckets.setdefault(
                row.symbol,
                {
                    "trade_count": 0,
                    "realized_pnl_usd": 0.0,
                    "expectancy_weighted_sum": 0.0,
                    "win_count": 0,
                    "loss_count": 0,
                },
            )
            bucket["trade_count"] = int(bucket["trade_count"]) + row.trade_count
            bucket["realized_pnl_usd"] = float(bucket["realized_pnl_usd"]) + row.realized_pnl_usd
            bucket["expectancy_weighted_sum"] = float(bucket["expectancy_weighted_sum"]) + (row.expectancy_usd * max(row.trade_count, 1))
            bucket["win_count"] = int(bucket["win_count"]) + row.win_count
            bucket["loss_count"] = int(bucket["loss_count"]) + row.loss_count

        for row in report.regime_performance:
            bucket = regime_buckets.setdefault(
                row.mode,
                {
                    "decision_count": 0,
                    "score_sum": 0.0,
                    "net_edge_sum": 0.0,
                    "cost_sum": 0.0,
                },
            )
            bucket["decision_count"] = int(bucket["decision_count"]) + row.decision_count
            bucket["score_sum"] = float(bucket["score_sum"]) + (row.avg_score * row.decision_count)
            bucket["net_edge_sum"] = float(bucket["net_edge_sum"]) + (row.avg_net_edge_bps * row.decision_count)
            bucket["cost_sum"] = float(bucket["cost_sum"]) + (row.avg_cost_bps * row.decision_count)

    symbol_rows: list[dict[str, object]] = []
    for symbol, bucket in symbol_buckets.items():
        trade_count = int(bucket["trade_count"])
        expectancy = float(bucket["expectancy_weighted_sum"]) / max(trade_count, 1)
        pnl = float(bucket["realized_pnl_usd"])
        recommendation = "keep"
        if trade_count >= 3 and expectancy < 0:
            recommendation = "prune"
        elif trade_count == 0:
            recommendation = "observe_only"
        elif trade_count >= 3 and expectancy > 0 and pnl > 0:
            recommendation = "promote"
        symbol_rows.append(
            {
                "symbol": symbol,
                "trade_count": trade_count,
                "realized_pnl_usd": round(pnl, 6),
                "expectancy_usd": round(expectancy, 6),
                "win_count": int(bucket["win_count"]),
                "loss_count": int(bucket["loss_count"]),
                "recommendation": recommendation,
            }
        )
    symbol_rows.sort(key=lambda item: (str(item["recommendation"]), float(item["expectancy_usd"])))

    regime_rows: list[dict[str, object]] = []
    for mode, bucket in regime_buckets.items():
        count = int(bucket["decision_count"])
        regime_rows.append(
            {
                "mode": mode,
                "decision_count": count,
                "avg_score": round(float(bucket["score_sum"]) / max(count, 1), 6),
                "avg_net_edge_bps": round(float(bucket["net_edge_sum"]) / max(count, 1), 6),
                "avg_cost_bps": round(float(bucket["cost_sum"]) / max(count, 1), 6),
            }
        )
    regime_rows.sort(key=lambda item: str(item["mode"]))

    return WeeklyValidationReport(
        base_dir=str(root),
        generated_at=generated_at,
        lookback_days=lookback_days,
        run_count=len(runs),
        period_start=datetime.fromtimestamp(runs[0].stat().st_mtime, tz=UTC).isoformat(),
        period_end=datetime.fromtimestamp(runs[-1].stat().st_mtime, tz=UTC).isoformat(),
        total_closed_trade_count=total_closed_trade_count,
        total_realized_pnl_usd=round(total_realized_pnl, 6),
        total_live_order_count=total_live_orders,
        total_tested_order_count=total_tested_orders,
        symbol_summary=tuple(symbol_rows),
        regime_summary=tuple(regime_rows),
        criteria=_criteria_table(),
    )






def _policy_adjustment_score(policy: dict[str, Any]) -> float:
    adjustments = list(dict(policy or {}).get("adjustments", []) or [])
    score = 0.0
    for item in adjustments:
        score += float(item.get("size_multiplier", 1.0) or 1.0) - 1.0
        score += float(item.get("leverage_multiplier", 1.0) or 1.0) - 1.0
        score -= float(item.get("entry_threshold_bps", 0.0) or 0.0) / 10.0
        score -= float(item.get("expected_profit_floor_bps", 0.0) or 0.0) / 10.0
        score += float(item.get("score_delta", 0.0) or 0.0)
    return round(score, 6)


def _replay_summary_from_evidence(
    evidence: dict[str, Any],
    *,
    run_count: int | None = None,
) -> dict[str, object]:
    payload = dict(evidence or {})
    symbol_summary = list(payload.get("symbol_summary", []) or [])
    regime_summary = list(payload.get("regime_summary", []) or [])
    walk_forward_window_count = _safe_int(payload.get("runner_walk_forward_window_count"))
    positive_walk_forward_window_count = _safe_int(payload.get("runner_positive_walk_forward_window_count"))
    return {
        "run_count": _safe_int(run_count if run_count is not None else payload.get("run_count")),
        "walk_forward_window_count": walk_forward_window_count,
        "positive_walk_forward_window_count": positive_walk_forward_window_count,
        "positive_walk_forward_ratio": round(
            _safe_float(
                payload.get(
                    "runner_positive_walk_forward_ratio",
                    _safe_ratio(positive_walk_forward_window_count, walk_forward_window_count),
                )
            ),
            6,
        ),
        "micro_live_gate": dict(payload.get("micro_live_gate", {}) or {}),
        "top_symbols": symbol_summary[:3],
        "top_regimes": regime_summary[:3],
    }


def _replay_summary_available(summary: dict[str, Any]) -> bool:
    payload = dict(summary or {})
    return bool(
        _safe_int(payload.get("run_count")) > 0
        or _safe_int(payload.get("walk_forward_window_count")) > 0
        or list(payload.get("top_symbols", []) or [])
        or list(payload.get("top_regimes", []) or [])
        or bool(dict(payload.get("micro_live_gate", {}) or {}).get("available"))
    )


def _counterfactual_replay_path(
    *,
    validation_mode: str,
    candidate_policy_score: float,
    current_policy_score: float,
    candidate_replay_summary: dict[str, object],
    current_replay_summary: dict[str, object],
    current_evidence_available: bool,
) -> dict[str, object]:
    candidate_summary = dict(candidate_replay_summary or {})
    current_summary = dict(current_replay_summary or {})
    return {
        "mode": "counterfactual_current_vs_candidate_policy",
        "validation_mode": validation_mode,
        "candidate_policy": {
            "policy_label": "candidate_policy",
            "source": "policy_validation_runner_artifact",
            "policy_score": round(candidate_policy_score, 6),
            "evidence_available": _replay_summary_available(candidate_summary),
            "replay_summary": candidate_summary,
        },
        "current_policy": {
            "policy_label": "current_policy",
            "source": "persisted_policy_validation_evidence",
            "policy_score": round(current_policy_score, 6),
            "evidence_available": current_evidence_available and _replay_summary_available(current_summary),
            "replay_summary": current_summary,
        },
    }


def build_policy_comparison_validation_artifact(*,
    current_policy_state: dict[str, Any] | None,
    candidate_policy: dict[str, Any],
    base_dir: str | Path = "quant_runtime",
    lookback_days: int = 7,
) -> dict[str, object]:
    runner = build_policy_validation_runner_artifact(base_dir=base_dir, lookback_days=lookback_days)
    runner_evidence = dict(runner.get("evidence", {}) or {})
    current_policy = dict(dict(current_policy_state or {}).get("active_policy", {}) or {})
    current_policy_evidence = dict(dict(dict(current_policy_state or {}).get("policy_validation", {}) or {}).get("evidence", {}) or {})
    current_score = _policy_adjustment_score(current_policy)
    candidate_score = _policy_adjustment_score(candidate_policy)
    delta = round(candidate_score - current_score, 6)
    structural_verdict = "keep"
    if delta > 0.1:
        structural_verdict = "candidate_better"
    elif delta < -0.1:
        structural_verdict = "candidate_worse"
    runtime_comparison = _compare_runtime_evidence(
        candidate_evidence=runner_evidence,
        current_evidence=current_policy_evidence,
    )
    runtime_verdict = str(runtime_comparison.get("runtime_comparison_verdict", "keep"))
    verdict = runtime_verdict if runtime_verdict != "keep" else structural_verdict
    candidate_replay_summary = _replay_summary_from_evidence(
        {
            **runner_evidence,
            "symbol_summary": runner.get("symbol_summary", []),
            "regime_summary": runner.get("regime_summary", []),
            "micro_live_gate": runner.get("micro_live_gate", {}),
        },
        run_count=_safe_int(runner.get("run_count")),
    )
    current_replay_summary = _replay_summary_from_evidence(current_policy_evidence)
    validation_path = {
        "mode": str(runner.get("validation_path_mode", "artifact_walk_forward")),
        "candidate_run_count": _safe_int(runner.get("run_count")),
        "candidate_walk_forward_window_count": _safe_int(runner.get("runner_walk_forward_window_count")),
        "candidate_positive_walk_forward_ratio": round(_safe_float(runner.get("runner_positive_walk_forward_ratio")), 6),
        "current_evidence_available": bool(runtime_comparison.get("runtime_evidence_available")),
        "current_walk_forward_window_count": _safe_int(current_policy_evidence.get("runner_walk_forward_window_count")),
        "current_positive_walk_forward_ratio": round(_safe_float(current_policy_evidence.get("runner_positive_walk_forward_ratio")), 6),
        "compared_metrics": list(runtime_comparison.get("compared_metrics", [])),
    }
    counterfactual_replay_path = _counterfactual_replay_path(
        validation_mode=str(runner.get("validation_path_mode", "artifact_walk_forward")),
        candidate_policy_score=candidate_score,
        current_policy_score=current_score,
        candidate_replay_summary=candidate_replay_summary,
        current_replay_summary=current_replay_summary,
        current_evidence_available=bool(runtime_comparison.get("runtime_evidence_available")),
    )
    evidence = {
        "comparison_verdict": verdict,
        "comparison_structural_verdict": structural_verdict,
        "comparison_runtime_verdict": runtime_verdict,
        "candidate_policy_score": candidate_score,
        "current_policy_score": current_score,
        "candidate_vs_current_score_delta": delta,
        "runner_total_return_pct": runner.get("runner_total_return_pct", 0.0),
        "runner_total_realized_pnl_usd": runner.get("runner_total_realized_pnl_usd", 0.0),
        "runner_max_drawdown_pct": runner.get("runner_max_drawdown_pct", 0.0),
        "runner_max_drawdown_usd": runner.get("runner_max_drawdown_usd", 0.0),
        "runner_drawdown_to_pnl_ratio": runner.get("runner_drawdown_to_pnl_ratio", 0.0),
        "runner_shadow_alignment_score": runner.get("runner_shadow_alignment_score", 0.0),
        "runner_reject_rate": runner.get("runner_reject_rate", 0.0),
        "runner_avg_slippage_bps": runner.get("runner_avg_slippage_bps", 0.0),
        "runner_avg_realized_edge_bps": runner.get("runner_avg_realized_edge_bps", 0.0),
        "runner_avg_edge_retention_ratio": runner.get("runner_avg_edge_retention_ratio", 0.0),
        "runner_positive_walk_forward_ratio": runner.get("runner_positive_walk_forward_ratio", 0.0),
        "micro_live_gate": runner.get("micro_live_gate", {}),
        "candidate_vs_current_validation_path": validation_path,
        "counterfactual_replay_path": counterfactual_replay_path,
        "candidate_replay_summary": candidate_replay_summary,
        "current_replay_summary": current_replay_summary,
        "symbol_summary": runner.get("symbol_summary", []),
        "regime_summary": runner.get("regime_summary", []),
        "pruning_recommendations": runner.get("pruning_recommendations", []),
        "walk_forward_windows": runner.get("walk_forward_windows", []),
        "validation_runs": runner.get("validation_runs", []),
        **runtime_comparison,
    }
    return {
        "generated_at": runner.get("generated_at"),
        "comparison_verdict": verdict,
        "candidate_policy_score": candidate_score,
        "current_policy_score": current_score,
        "candidate_vs_current_score_delta": delta,
        "runner_total_return_pct": runner.get("runner_total_return_pct", 0.0),
        "runner_total_realized_pnl_usd": runner.get("runner_total_realized_pnl_usd", 0.0),
        "runner_max_drawdown_pct": runner.get("runner_max_drawdown_pct", 0.0),
        "runner_max_drawdown_usd": runner.get("runner_max_drawdown_usd", 0.0),
        "runner_drawdown_to_pnl_ratio": runner.get("runner_drawdown_to_pnl_ratio", 0.0),
        "runner_shadow_alignment_score": runner.get("runner_shadow_alignment_score", 0.0),
        "runner_reject_rate": runner.get("runner_reject_rate", 0.0),
        "runner_avg_slippage_bps": runner.get("runner_avg_slippage_bps", 0.0),
        "runner_avg_realized_edge_bps": runner.get("runner_avg_realized_edge_bps", 0.0),
        "runner_avg_edge_retention_ratio": runner.get("runner_avg_edge_retention_ratio", 0.0),
        "runner_positive_walk_forward_ratio": runner.get("runner_positive_walk_forward_ratio", 0.0),
        "counterfactual_replay_path": counterfactual_replay_path,
        "candidate_replay_summary": candidate_replay_summary,
        "current_replay_summary": current_replay_summary,
        "validation_path": validation_path,
        "evidence": evidence,
    }


def write_policy_comparison_validation_artifact(*,
    current_policy_state: dict[str, Any] | None,
    candidate_policy: dict[str, Any],
    base_dir: str | Path = "quant_runtime",
    output_path: str | Path,
    lookback_days: int = 7,
) -> Path:
    artifact = build_policy_comparison_validation_artifact(
        current_policy_state=current_policy_state,
        candidate_policy=candidate_policy,
        base_dir=base_dir,
        lookback_days=lookback_days,
    )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    return target

def build_policy_validation_runner_artifact(*, base_dir: str | Path = "quant_runtime", lookback_days: int = 7) -> dict[str, object]:
    report = build_weekly_validation_report(base_dir=base_dir, lookback_days=lookback_days)
    runs = _resolve_recent_runs(base_dir=Path(base_dir), lookback_days=lookback_days)
    run_snapshots = [_run_validation_snapshot(run_dir=run_dir) for run_dir in runs]
    symbol_rows = list(report.symbol_summary)
    regime_rows = list(report.regime_summary)
    pruning_recommendations = _aggregate_pruning_recommendations(run_snapshots)
    promote_count = sum(1 for row in symbol_rows if str(row.get("recommendation", "")) == "promote")
    prune_count = sum(1 for row in symbol_rows if str(row.get("recommendation", "")) == "prune")
    total_symbols = max(len(symbol_rows), 1)
    walk_forward_windows = [window for snapshot in run_snapshots for window in list(snapshot.get("walk_forward", []))]
    positive_walk_forward_count = sum(
        1
        for window in walk_forward_windows
        if _safe_float(window.get("avg_net_edge_bps")) > 0.0 and _safe_float(window.get("avg_score")) >= 0.0
    )
    walk_forward_alignment = (
        positive_walk_forward_count / len(walk_forward_windows)
        if walk_forward_windows
        else (1.0 if report.run_count > 0 and report.total_realized_pnl_usd > 0.0 else 0.0)
    )
    shadow_alignment_score = max(
        0.0,
        min(1.0, ((promote_count - prune_count + total_symbols) / (2 * total_symbols) * 0.5) + (walk_forward_alignment * 0.5)),
    )
    pnl_series = [_safe_float(snapshot.get("realized_pnl_usd")) for snapshot in run_snapshots]
    total_realized_pnl_usd = round(sum(pnl_series), 6)
    max_drawdown_usd = _max_drawdown(pnl_series)
    drawdown_to_pnl_ratio = round(max_drawdown_usd / max(abs(total_realized_pnl_usd), 1.0), 6)
    live_order_count = sum(_safe_int(snapshot.get("live_order_count")) for snapshot in run_snapshots)
    rejected_live_order_count = sum(_safe_int(snapshot.get("rejected_live_order_count")) for snapshot in run_snapshots)
    closed_trade_count = sum(_safe_int(snapshot.get("closed_trade_count")) for snapshot in run_snapshots)
    slippage_weight = float(sum(_safe_int(snapshot.get("accepted_live_order_count")) for snapshot in run_snapshots))
    retention_weight = float(sum(_safe_int(snapshot.get("live_order_count")) for snapshot in run_snapshots))
    avg_slippage_bps = _weighted_metric(
        sum(_safe_float(snapshot.get("avg_slippage_bps")) * _safe_int(snapshot.get("accepted_live_order_count")) for snapshot in run_snapshots),
        slippage_weight,
    )
    avg_realized_edge_bps = _weighted_metric(
        sum(_safe_float(snapshot.get("avg_realized_edge_bps")) * _safe_int(snapshot.get("live_order_count")) for snapshot in run_snapshots),
        retention_weight,
    )
    avg_edge_retention_ratio = _weighted_metric(
        sum(_safe_float(snapshot.get("avg_edge_retention_ratio")) * _safe_int(snapshot.get("live_order_count")) for snapshot in run_snapshots),
        retention_weight,
    )
    reject_rate = round(rejected_live_order_count / max(live_order_count, 1), 6) if live_order_count > 0 else 0.0
    micro_live_gate = _build_micro_live_gate(
        live_order_count=live_order_count,
        rejected_live_order_count=rejected_live_order_count,
        avg_slippage_bps=avg_slippage_bps,
        avg_realized_edge_bps=avg_realized_edge_bps,
        closed_trade_count=closed_trade_count,
    )
    total_return_pct = total_realized_pnl_usd
    max_drawdown_pct = max_drawdown_usd
    evidence = {
        "runner_total_return_pct": total_return_pct,
        "runner_total_realized_pnl_usd": total_realized_pnl_usd,
        "runner_max_drawdown_pct": max_drawdown_pct,
        "runner_max_drawdown_usd": max_drawdown_usd,
        "runner_drawdown_to_pnl_ratio": drawdown_to_pnl_ratio,
        "runner_shadow_alignment_score": round(shadow_alignment_score, 6),
        "runner_reject_rate": reject_rate,
        "runner_avg_slippage_bps": avg_slippage_bps,
        "runner_avg_realized_edge_bps": avg_realized_edge_bps,
        "runner_avg_edge_retention_ratio": avg_edge_retention_ratio,
        "runner_walk_forward_window_count": len(walk_forward_windows),
        "runner_positive_walk_forward_window_count": positive_walk_forward_count,
        "runner_positive_walk_forward_ratio": round(_safe_ratio(positive_walk_forward_count, len(walk_forward_windows)), 6),
        "micro_live_gate": micro_live_gate,
    }
    return {
        "generated_at": report.generated_at,
        "lookback_days": report.lookback_days,
        "run_count": report.run_count,
        "validation_path_mode": "paper_live_walk_forward_artifacts",
        "runner_total_return_pct": total_return_pct,
        "runner_total_realized_pnl_usd": total_realized_pnl_usd,
        "runner_max_drawdown_pct": max_drawdown_pct,
        "runner_max_drawdown_usd": max_drawdown_usd,
        "runner_drawdown_to_pnl_ratio": drawdown_to_pnl_ratio,
        "runner_shadow_alignment_score": round(shadow_alignment_score, 6),
        "runner_reject_rate": reject_rate,
        "runner_avg_slippage_bps": avg_slippage_bps,
        "runner_avg_realized_edge_bps": avg_realized_edge_bps,
        "runner_avg_edge_retention_ratio": avg_edge_retention_ratio,
        "runner_walk_forward_window_count": len(walk_forward_windows),
        "runner_positive_walk_forward_window_count": positive_walk_forward_count,
        "runner_positive_walk_forward_ratio": round(_safe_ratio(positive_walk_forward_count, len(walk_forward_windows)), 6),
        "validation_runs": run_snapshots,
        "walk_forward_windows": walk_forward_windows,
        "symbol_summary": symbol_rows,
        "regime_summary": regime_rows,
        "pruning_recommendations": pruning_recommendations,
        "micro_live_gate": micro_live_gate,
        "evidence": evidence,
    }


def write_policy_validation_runner_artifact(*, base_dir: str | Path = "quant_runtime", output_path: str | Path, lookback_days: int = 7) -> Path:
    artifact = build_policy_validation_runner_artifact(base_dir=base_dir, lookback_days=lookback_days)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2, sort_keys=True), encoding="utf-8")
    return target

def write_weekly_validation_report(*, report: WeeklyValidationReport, output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return target
