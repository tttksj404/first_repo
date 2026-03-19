from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from quant_binance.observability.report import load_validation_runner_evidence
from quant_binance.policy_evidence import build_replay_provenance


@dataclass(frozen=True)
class ExecutionQualityReport:
    base_dir: str
    generated_at: str
    lookback_days: int
    run_count: int
    live_order_count: int
    tested_order_count: int
    order_error_count: int
    accepted_live_order_count: int
    estimated_live_acceptance_rate: float
    reject_rate: float
    avg_slippage_bps: float
    avg_realized_edge_bps: float
    avg_edge_retention_ratio: float
    protection_degraded_rate: float
    sample_quality_watchdog_status: str
    sample_quality_watchdog_reasons: tuple[str, ...]
    auto_mode: str
    auto_mode_reasons: tuple[str, ...]
    executive_verdict: str
    executive_reason_codes: tuple[str, ...]
    executive_replay_provenance: dict[str, object]
    top_error_codes: tuple[dict[str, object], ...]
    policy_bucket_summary: tuple[dict[str, object], ...]
    symbol_order_summary: tuple[dict[str, object], ...]
    top_symbols: tuple[dict[str, object], ...]
    checkpoint_symbols: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "base_dir": self.base_dir,
            "generated_at": self.generated_at,
            "lookback_days": self.lookback_days,
            "run_count": self.run_count,
            "live_order_count": self.live_order_count,
            "tested_order_count": self.tested_order_count,
            "order_error_count": self.order_error_count,
            "accepted_live_order_count": self.accepted_live_order_count,
            "estimated_live_acceptance_rate": self.estimated_live_acceptance_rate,
            "reject_rate": self.reject_rate,
            "avg_slippage_bps": self.avg_slippage_bps,
            "avg_realized_edge_bps": self.avg_realized_edge_bps,
            "avg_edge_retention_ratio": self.avg_edge_retention_ratio,
            "protection_degraded_rate": self.protection_degraded_rate,
            "sample_quality_watchdog_status": self.sample_quality_watchdog_status,
            "sample_quality_watchdog_reasons": list(self.sample_quality_watchdog_reasons),
            "auto_mode": self.auto_mode,
            "auto_mode_reasons": list(self.auto_mode_reasons),
            "executive_verdict": self.executive_verdict,
            "executive_reason_codes": list(self.executive_reason_codes),
            "executive_replay_provenance": dict(self.executive_replay_provenance),
            "top_error_codes": list(self.top_error_codes),
            "policy_bucket_summary": list(self.policy_bucket_summary),
            "symbol_order_summary": list(self.symbol_order_summary),
            "top_symbols": list(self.top_symbols),
            "checkpoint_symbols": list(self.checkpoint_symbols),
        }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_recent_runs(*, base_dir: Path, lookback_days: int) -> list[Path]:
    mode_root = base_dir / "output" / "paper-live-shell"
    if not mode_root.exists():
        return []
    threshold = datetime.now(UTC) - timedelta(days=lookback_days)
    runs: list[Path] = []
    for candidate in mode_root.iterdir():
        if not candidate.is_dir() or candidate.name == "latest":
            continue
        modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
        if modified >= threshold:
            runs.append(candidate)
    runs.sort(key=lambda p: p.stat().st_mtime)
    return runs


def _extract_error_code(message: str) -> str:
    if '"code":"' in message:
        try:
            return message.split('"code":"', 1)[1].split('"', 1)[0]
        except Exception:
            pass
    if '"code":' in message:
        try:
            tail = message.split('"code":', 1)[1].lstrip()
            digits = []
            for char in tail:
                if char.isdigit():
                    digits.append(char)
                    continue
                if digits:
                    break
            if digits:
                return "".join(digits)
        except Exception:
            pass
    for token in message.replace('"', " ").replace(":", " ").split():
        if token.isdigit():
            return token
    return "unknown"


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _edge_retention_ratio(realized_edge_bps: float | None, expected_edge_bps: float | None) -> float | None:
    if realized_edge_bps is None or expected_edge_bps is None:
        return None
    baseline = max(float(expected_edge_bps), 0.0)
    if baseline <= 0.0:
        return None
    return max(min(float(realized_edge_bps) / max(baseline, 0.1), 2.0), -2.0)


def _symbol_checkpoint_map(watchdog: dict[str, object]) -> dict[str, dict[str, object]]:
    snapshot = dict(watchdog.get("checkpoint_snapshot", {}) or {})
    return {
        str(row.get("symbol", "") or ""): dict(row)
        for row in list(snapshot.get("symbols", []) or [])
        if isinstance(row, dict) and str(row.get("symbol", "") or "")
    }


def _empty_execution_bucket() -> dict[str, float | int]:
    return {
        "live_order_count": 0,
        "accepted_live_order_count": 0,
        "rejected_live_order_count": 0,
        "tested_order_count": 0,
        "order_error_count": 0,
        "slippage_sum": 0.0,
        "slippage_count": 0,
        "realized_edge_sum": 0.0,
        "realized_edge_count": 0,
        "retention_sum": 0.0,
        "retention_count": 0,
        "protection_degraded_count": 0,
    }


def _summarize_execution_bucket(*, label: str, bucket: dict[str, float | int], label_key: str) -> dict[str, object]:
    live_count = int(bucket["live_order_count"])
    accepted_count = int(bucket["accepted_live_order_count"])
    rejected_count = int(bucket["rejected_live_order_count"])
    slippage_count = int(bucket["slippage_count"])
    realized_edge_count = int(bucket["realized_edge_count"])
    retention_count = int(bucket["retention_count"])
    return {
        label_key: label,
        "live_order_count": live_count,
        "accepted_live_order_count": accepted_count,
        "rejected_live_order_count": rejected_count,
        "tested_order_count": int(bucket["tested_order_count"]),
        "order_error_count": int(bucket["order_error_count"]),
        "estimated_live_acceptance_rate": round(accepted_count / live_count, 6) if live_count else 0.0,
        "reject_rate": round(rejected_count / live_count, 6) if live_count else 0.0,
        "avg_slippage_bps": round(float(bucket["slippage_sum"]) / slippage_count, 6) if slippage_count else 0.0,
        "avg_realized_edge_bps": round(float(bucket["realized_edge_sum"]) / realized_edge_count, 6) if realized_edge_count else 0.0,
        "avg_edge_retention_ratio": round(float(bucket["retention_sum"]) / retention_count, 6) if retention_count else 0.0,
        "protection_degraded_count": int(bucket["protection_degraded_count"]),
    }


def build_execution_quality_report(*, base_dir: str | Path = "quant_runtime", lookback_days: int = 7) -> ExecutionQualityReport:
    root = Path(base_dir)
    runs = _resolve_recent_runs(base_dir=root, lookback_days=lookback_days)
    generated_at = datetime.now(UTC).isoformat()

    live_order_count = 0
    tested_order_count = 0
    order_error_count = 0
    accepted_live_order_count = 0
    rejected_live_order_count = 0
    error_codes: Counter[str] = Counter()
    slippage_values: list[float] = []
    realized_edge_values: list[float] = []
    retention_values: list[float] = []
    protection_degraded_count = 0
    by_symbol: dict[str, dict[str, float | int]] = defaultdict(_empty_execution_bucket)
    by_policy_bucket: dict[str, dict[str, float | int]] = defaultdict(_empty_execution_bucket)
    latest_validation_evidence: dict[str, object] = {}
    latest_policy_state: dict[str, object] = {}
    latest_summary: dict[str, object] = {}

    for run_dir in runs:
        logs_dir = run_dir / "logs"
        live_orders = _load_jsonl(logs_dir / "live_orders.jsonl")
        tested_orders = _load_jsonl(logs_dir / "tested_orders.jsonl")
        order_errors = _load_jsonl(logs_dir / "order_errors.jsonl")
        validation_evidence = load_validation_runner_evidence(run_dir / "validation_report.json")
        if validation_evidence:
            latest_validation_evidence = validation_evidence
        latest_policy_state = _load_json(run_dir / "policy_state.json")
        latest_summary = _load_json(run_dir / "summary.json")

        live_order_count += len(live_orders)
        tested_order_count += len(tested_orders)
        order_error_count += len(order_errors)

        for row in live_orders:
            symbol = str(row.get("symbol", ""))
            policy_bucket = str(row.get("entry_policy_bucket", "") or "").strip().lower()
            accepted = bool(row.get("accepted", False))
            if accepted:
                accepted_live_order_count += 1
            else:
                rejected_live_order_count += 1
            bucket = by_symbol[symbol]
            policy_bucket_metrics = by_policy_bucket[policy_bucket] if policy_bucket else None
            bucket["live_order_count"] = int(bucket["live_order_count"]) + 1
            if policy_bucket_metrics is not None:
                policy_bucket_metrics["live_order_count"] = int(policy_bucket_metrics["live_order_count"]) + 1
            if accepted:
                bucket["accepted_live_order_count"] = int(bucket["accepted_live_order_count"]) + 1
                if policy_bucket_metrics is not None:
                    policy_bucket_metrics["accepted_live_order_count"] = int(policy_bucket_metrics["accepted_live_order_count"]) + 1
            else:
                bucket["rejected_live_order_count"] = int(bucket["rejected_live_order_count"]) + 1
                if policy_bucket_metrics is not None:
                    policy_bucket_metrics["rejected_live_order_count"] = int(policy_bucket_metrics["rejected_live_order_count"]) + 1
            slippage = row.get("slippage_bps")
            if slippage is not None:
                slip = _safe_float(slippage)
                slippage_values.append(slip)
                bucket["slippage_sum"] = float(bucket["slippage_sum"]) + slip
                bucket["slippage_count"] = int(bucket["slippage_count"]) + 1
                if policy_bucket_metrics is not None:
                    policy_bucket_metrics["slippage_sum"] = float(policy_bucket_metrics["slippage_sum"]) + slip
                    policy_bucket_metrics["slippage_count"] = int(policy_bucket_metrics["slippage_count"]) + 1
            realized_edge = row.get("realized_edge_bps")
            expected_edge = row.get("expected_net_edge_bps", row.get("net_expected_edge_bps"))
            if realized_edge is not None:
                realized = _safe_float(realized_edge)
                realized_edge_values.append(realized)
                bucket["realized_edge_sum"] = float(bucket["realized_edge_sum"]) + realized
                bucket["realized_edge_count"] = int(bucket["realized_edge_count"]) + 1
                if policy_bucket_metrics is not None:
                    policy_bucket_metrics["realized_edge_sum"] = float(policy_bucket_metrics["realized_edge_sum"]) + realized
                    policy_bucket_metrics["realized_edge_count"] = int(policy_bucket_metrics["realized_edge_count"]) + 1
                retention = _edge_retention_ratio(realized, _safe_float(expected_edge, None)) if expected_edge is not None else None
                if retention is not None:
                    retention_values.append(retention)
                    bucket["retention_sum"] = float(bucket["retention_sum"]) + retention
                    bucket["retention_count"] = int(bucket["retention_count"]) + 1
                    if policy_bucket_metrics is not None:
                        policy_bucket_metrics["retention_sum"] = float(policy_bucket_metrics["retention_sum"]) + retention
                        policy_bucket_metrics["retention_count"] = int(policy_bucket_metrics["retention_count"]) + 1
            if row.get("protection_error"):
                protection_degraded_count += 1
                bucket["protection_degraded_count"] = int(bucket["protection_degraded_count"]) + 1
                if policy_bucket_metrics is not None:
                    policy_bucket_metrics["protection_degraded_count"] = int(policy_bucket_metrics["protection_degraded_count"]) + 1

        for row in tested_orders:
            symbol = str(row.get("symbol", ""))
            bucket = by_symbol[symbol]
            bucket["tested_order_count"] = int(bucket["tested_order_count"]) + 1
            policy_bucket = str(row.get("entry_policy_bucket", "") or "").strip().lower()
            if policy_bucket:
                by_policy_bucket[policy_bucket]["tested_order_count"] = int(by_policy_bucket[policy_bucket]["tested_order_count"]) + 1

        for row in order_errors:
            symbol = str(row.get("symbol", ""))
            message = str(row.get("error_message") or row.get("response") or "")
            code = _extract_error_code(message)
            error_codes[code] += 1
            bucket = by_symbol[symbol]
            bucket["order_error_count"] = int(bucket["order_error_count"]) + 1
            policy_bucket = str(row.get("entry_policy_bucket", "") or "").strip().lower()
            if policy_bucket:
                by_policy_bucket[policy_bucket]["order_error_count"] = int(by_policy_bucket[policy_bucket]["order_error_count"]) + 1

    symbol_rows: list[dict[str, object]] = []
    for symbol, bucket in by_symbol.items():
        symbol_rows.append(_summarize_execution_bucket(label=symbol, bucket=bucket, label_key="symbol"))
    symbol_rows.sort(
        key=lambda item: (
            -int(item["order_error_count"]),
            float(item["reject_rate"]),
            str(item["symbol"]),
        )
    )
    policy_bucket_rows = [
        _summarize_execution_bucket(label=policy_bucket, bucket=bucket, label_key="policy_bucket")
        for policy_bucket, bucket in by_policy_bucket.items()
        if policy_bucket
    ]
    policy_bucket_rows.sort(
        key=lambda item: (
            -int(item["live_order_count"]),
            float(item["reject_rate"]),
            str(item["policy_bucket"]),
        )
    )

    top_error_codes = tuple(
        {"code": code, "count": count}
        for code, count in error_codes.most_common(10)
    )

    acceptance_rate = round(accepted_live_order_count / live_order_count, 6) if live_order_count else 0.0
    reject_rate = round(rejected_live_order_count / live_order_count, 6) if live_order_count else 0.0
    watchdog = dict(latest_validation_evidence.get("sample_quality_watchdog", {}) or {})
    auto_mode = dict(latest_validation_evidence.get("auto_mode", {}) or {})
    executive_operating_verdict = dict(
        latest_policy_state.get(
            "executive_operating_verdict",
            latest_summary.get("executive_operating_verdict", latest_validation_evidence.get("executive_operating_verdict", {})),
        )
        or {}
    )
    executive_replay_provenance = dict(executive_operating_verdict.get("replay_provenance", {}) or {})
    if not executive_replay_provenance:
        executive_replay_provenance = {"primary": build_replay_provenance()}
    checkpoint_by_symbol = _symbol_checkpoint_map(watchdog)
    top_symbols = tuple(
        {
            "symbol": str(row.get("symbol", "") or ""),
            "expectancy_usd": round(_safe_float(row.get("expectancy_usd")), 6),
            "trade_count": _safe_int(row.get("trade_count")),
            "recommendation": str(row.get("recommendation", "keep") or "keep"),
            "sample_status": str(row.get("sample_status", "") or ""),
            "validation_ready": bool(
                dict(checkpoint_by_symbol.get(str(row.get("symbol", "") or ""), {})).get("validation_ready", False)
            )
            or _safe_int(row.get("trade_count")) >= max(_safe_int(row.get("required_trade_count_for_validation"), 3), 1),
        }
        for row in list(latest_validation_evidence.get("symbol_summary", []) or [])[:3]
        if isinstance(row, dict) and str(row.get("symbol", "") or "")
    )
    checkpoint_rows = list(dict(watchdog.get("checkpoint_snapshot", {}) or {}).get("symbols", []) or [])
    if not checkpoint_rows:
        checkpoint_rows = [
            {
                "symbol": str(row.get("symbol", "") or ""),
                "trade_count": _safe_int(row.get("trade_count")),
                "validation_threshold": max(_safe_int(row.get("required_trade_count_for_validation"), 3), 1),
                "validation_ready": _safe_int(row.get("trade_count")) >= max(_safe_int(row.get("required_trade_count_for_validation"), 3), 1),
            }
            for row in list(latest_validation_evidence.get("symbol_summary", []) or [])
            if isinstance(row, dict) and str(row.get("symbol", "") or "")
        ]
    checkpoint_symbols = tuple(
        {
            "symbol": str(row.get("symbol", "") or ""),
            "trade_count": _safe_int(row.get("trade_count")),
            "validation_threshold": _safe_int(row.get("validation_threshold"), 0),
            "validation_ready": bool(row.get("validation_ready", False)),
        }
        for row in checkpoint_rows
        if isinstance(row, dict) and str(row.get("symbol", "") or "")
    )
    return ExecutionQualityReport(
        base_dir=str(root),
        generated_at=generated_at,
        lookback_days=lookback_days,
        run_count=len(runs),
        live_order_count=live_order_count,
        tested_order_count=tested_order_count,
        order_error_count=order_error_count,
        accepted_live_order_count=accepted_live_order_count,
        estimated_live_acceptance_rate=acceptance_rate,
        reject_rate=reject_rate,
        avg_slippage_bps=round(sum(slippage_values) / len(slippage_values), 6) if slippage_values else 0.0,
        avg_realized_edge_bps=round(sum(realized_edge_values) / len(realized_edge_values), 6) if realized_edge_values else 0.0,
        avg_edge_retention_ratio=round(sum(retention_values) / len(retention_values), 6) if retention_values else 0.0,
        protection_degraded_rate=round(protection_degraded_count / live_order_count, 6) if live_order_count else 0.0,
        sample_quality_watchdog_status=str(watchdog.get("status", "") or ""),
        sample_quality_watchdog_reasons=tuple(str(item) for item in list(watchdog.get("reason_codes", []) or [])),
        auto_mode=str(auto_mode.get("mode", "normal") or "normal"),
        auto_mode_reasons=tuple(str(item) for item in list(auto_mode.get("reason_codes", []) or [])),
        executive_verdict=str(executive_operating_verdict.get("verdict", "not_available") or "not_available"),
        executive_reason_codes=tuple(str(item) for item in list(executive_operating_verdict.get("reasons", []) or [])),
        executive_replay_provenance=executive_replay_provenance,
        top_error_codes=top_error_codes,
        policy_bucket_summary=tuple(policy_bucket_rows),
        symbol_order_summary=tuple(symbol_rows),
        top_symbols=top_symbols,
        checkpoint_symbols=checkpoint_symbols,
    )


def write_execution_quality_report(*, report: ExecutionQualityReport, output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return target
