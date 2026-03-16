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


def write_weekly_validation_report(*, report: WeeklyValidationReport, output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return target
