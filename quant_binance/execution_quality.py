from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from quant_binance.models import DecisionIntent


MIN_EXECUTION_QUALITY_SAMPLE_SIZE = 3


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


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


def _running_average(current_avg: float, current_count: int, sample: float) -> float:
    if current_count <= 0:
        return sample
    return ((current_avg * current_count) + sample) / (current_count + 1)


@dataclass(frozen=True)
class ExecutionQualityMetrics:
    attempts: int = 0
    fills: int = 0
    partial_fills: int = 0
    rejects: int = 0
    timeouts: int = 0
    avg_slippage_bps: float = 0.0
    avg_fill_ratio: float = 1.0
    avg_realized_edge_bps: float = 0.0
    last_updated_time: str = ""
    slippage_sample_count: int = 0
    fill_ratio_sample_count: int = 0
    realized_edge_sample_count: int = 0

    @classmethod
    def from_dict(cls, payload: dict[str, object] | None) -> "ExecutionQualityMetrics":
        if not isinstance(payload, dict):
            return cls()
        return cls(
            attempts=_safe_int(payload.get("attempts")),
            fills=_safe_int(payload.get("fills")),
            partial_fills=_safe_int(payload.get("partial_fills")),
            rejects=_safe_int(payload.get("rejects")),
            timeouts=_safe_int(payload.get("timeouts")),
            avg_slippage_bps=_safe_float(payload.get("avg_slippage_bps")),
            avg_fill_ratio=_safe_float(payload.get("avg_fill_ratio"), 1.0),
            avg_realized_edge_bps=_safe_float(payload.get("avg_realized_edge_bps")),
            last_updated_time=str(payload.get("last_updated_time") or ""),
            slippage_sample_count=_safe_int(payload.get("slippage_sample_count")),
            fill_ratio_sample_count=_safe_int(payload.get("fill_ratio_sample_count")),
            realized_edge_sample_count=_safe_int(payload.get("realized_edge_sample_count")),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "attempts": self.attempts,
            "fills": self.fills,
            "partial_fills": self.partial_fills,
            "rejects": self.rejects,
            "timeouts": self.timeouts,
            "avg_slippage_bps": round(self.avg_slippage_bps, 6),
            "avg_fill_ratio": round(self.avg_fill_ratio, 6),
            "avg_realized_edge_bps": round(self.avg_realized_edge_bps, 6),
            "last_updated_time": self.last_updated_time,
            "slippage_sample_count": self.slippage_sample_count,
            "fill_ratio_sample_count": self.fill_ratio_sample_count,
            "realized_edge_sample_count": self.realized_edge_sample_count,
        }


@dataclass(frozen=True)
class ExecutionQualityOverlay:
    sample_size: int = 0
    size_multiplier: float = 1.0
    edge_penalty_bps: float = 0.0
    trade_restraint: str = "none"
    avg_slippage_bps: float = 0.0
    avg_fill_ratio: float = 1.0
    avg_realized_edge_bps: float = 0.0
    reject_rate: float = 0.0
    timeout_rate: float = 0.0
    partial_fill_rate: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "sample_size": self.sample_size,
            "size_multiplier": round(self.size_multiplier, 6),
            "edge_penalty_bps": round(self.edge_penalty_bps, 6),
            "trade_restraint": self.trade_restraint,
            "avg_slippage_bps": round(self.avg_slippage_bps, 6),
            "avg_fill_ratio": round(self.avg_fill_ratio, 6),
            "avg_realized_edge_bps": round(self.avg_realized_edge_bps, 6),
            "reject_rate": round(self.reject_rate, 6),
            "timeout_rate": round(self.timeout_rate, 6),
            "partial_fill_rate": round(self.partial_fill_rate, 6),
        }


class ExecutionQualityState:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._symbols: dict[str, ExecutionQualityMetrics] = {}
        self._load()
        self._persist()

    def _load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        symbols = payload.get("symbols")
        if not isinstance(symbols, dict):
            return
        for symbol, raw_metrics in symbols.items():
            self._symbols[str(symbol)] = ExecutionQualityMetrics.from_dict(
                raw_metrics if isinstance(raw_metrics, dict) else None
            )

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.snapshot()
        with NamedTemporaryFile("w", delete=False, dir=str(self.path.parent), encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            temp_path = Path(handle.name)
        temp_path.replace(self.path)

    def metrics_for(self, symbol: str) -> ExecutionQualityMetrics:
        return self._symbols.get(symbol, ExecutionQualityMetrics())

    def overlay_for(self, symbol: str) -> ExecutionQualityOverlay:
        metrics = self.metrics_for(symbol)
        attempts = max(metrics.attempts, 0)
        reject_rate = metrics.rejects / attempts if attempts else 0.0
        timeout_rate = metrics.timeouts / attempts if attempts else 0.0
        partial_fill_rate = metrics.partial_fills / attempts if attempts else 0.0
        if attempts < MIN_EXECUTION_QUALITY_SAMPLE_SIZE:
            return ExecutionQualityOverlay(
                sample_size=attempts,
                avg_slippage_bps=metrics.avg_slippage_bps,
                avg_fill_ratio=metrics.avg_fill_ratio,
                avg_realized_edge_bps=metrics.avg_realized_edge_bps,
                reject_rate=reject_rate,
                timeout_rate=timeout_rate,
                partial_fill_rate=partial_fill_rate,
            )

        size_multiplier = 1.0
        if metrics.avg_fill_ratio < 0.85 or partial_fill_rate >= 0.35:
            size_multiplier = min(size_multiplier, 0.8)
        if metrics.avg_slippage_bps > 8.0:
            size_multiplier = min(size_multiplier, 0.85)
        if metrics.avg_slippage_bps > 12.0 or metrics.avg_fill_ratio < 0.65 or partial_fill_rate >= 0.5:
            size_multiplier = min(size_multiplier, 0.6)

        edge_penalty_bps = 0.0
        reject_timeout_rate = reject_rate + timeout_rate
        if reject_timeout_rate >= 0.2:
            edge_penalty_bps = max(edge_penalty_bps, 2.0)
        if reject_timeout_rate >= 0.35:
            edge_penalty_bps = max(edge_penalty_bps, 4.0)
        if reject_timeout_rate >= 0.5:
            edge_penalty_bps = max(edge_penalty_bps, 6.0)
        if metrics.avg_realized_edge_bps < 0.0:
            edge_penalty_bps = max(edge_penalty_bps, min(abs(metrics.avg_realized_edge_bps), 4.0))

        trade_restraint = "none"
        if (
            reject_timeout_rate >= 0.6
            or metrics.avg_fill_ratio < 0.35
            or metrics.avg_slippage_bps > 20.0
            or (attempts >= 5 and metrics.avg_realized_edge_bps < -2.0)
        ):
            trade_restraint = "execution_quality_halt"
            size_multiplier = 0.0

        return ExecutionQualityOverlay(
            sample_size=attempts,
            size_multiplier=size_multiplier,
            edge_penalty_bps=edge_penalty_bps,
            trade_restraint=trade_restraint,
            avg_slippage_bps=metrics.avg_slippage_bps,
            avg_fill_ratio=metrics.avg_fill_ratio,
            avg_realized_edge_bps=metrics.avg_realized_edge_bps,
            reject_rate=reject_rate,
            timeout_rate=timeout_rate,
            partial_fill_rate=partial_fill_rate,
        )

    def apply_overlay(self, decision: DecisionIntent) -> DecisionIntent:
        overlay = self.overlay_for(decision.symbol)
        annotated = {
            "execution_quality_sample_size": overlay.sample_size,
            "execution_quality_size_multiplier": overlay.size_multiplier,
            "execution_quality_edge_penalty_bps": overlay.edge_penalty_bps,
            "execution_quality_trade_restraint": overlay.trade_restraint,
            "execution_quality_avg_slippage_bps": overlay.avg_slippage_bps,
            "execution_quality_avg_fill_ratio": overlay.avg_fill_ratio,
            "execution_quality_avg_realized_edge_bps": overlay.avg_realized_edge_bps,
            "execution_quality_reject_rate": overlay.reject_rate,
            "execution_quality_timeout_rate": overlay.timeout_rate,
            "execution_quality_partial_fill_rate": overlay.partial_fill_rate,
        }
        if decision.final_mode not in {"spot", "futures"} or decision.order_intent_notional_usd <= 0.0:
            return DecisionIntent(**(asdict(decision) | annotated))

        updated_mode = decision.final_mode
        updated_side = decision.side
        updated_stop = decision.stop_distance_bps
        updated_notional = round(
            max(decision.order_intent_notional_usd * overlay.size_multiplier, 0.0),
            6,
        )
        updated_net_edge_bps = round(decision.net_expected_edge_bps - overlay.edge_penalty_bps, 6)
        updated_reasons = set(decision.rejection_reasons)

        if overlay.trade_restraint != "none":
            updated_mode = "cash"
            updated_side = "flat"
            updated_stop = 0.0
            updated_notional = 0.0
            updated_reasons.add("EXECUTION_QUALITY_RESTRAINT")
        elif overlay.sample_size >= MIN_EXECUTION_QUALITY_SAMPLE_SIZE and updated_net_edge_bps <= 0.0:
            updated_mode = "cash"
            updated_side = "flat"
            updated_stop = 0.0
            updated_notional = 0.0
            updated_reasons.add("EXECUTION_QUALITY_EDGE_TOO_THIN")

        return DecisionIntent(
            **(
                asdict(decision)
                | annotated
                | {
                    "final_mode": updated_mode,
                    "side": updated_side,
                    "stop_distance_bps": updated_stop,
                    "order_intent_notional_usd": updated_notional,
                    "net_expected_edge_bps": updated_net_edge_bps,
                    "rejection_reasons": tuple(sorted(updated_reasons)),
                }
            )
        )

    def record(
        self,
        *,
        symbol: str,
        outcome: str,
        fill_ratio: float,
        slippage_bps: float | None,
        realized_edge_bps: float | None,
        timestamp: datetime | None = None,
    ) -> ExecutionQualityMetrics:
        metrics = self.metrics_for(symbol)
        updated = ExecutionQualityMetrics(
            attempts=metrics.attempts + 1,
            fills=metrics.fills + (1 if outcome == "filled" else 0),
            partial_fills=metrics.partial_fills + (1 if outcome == "partial_fill" else 0),
            rejects=metrics.rejects + (1 if outcome == "reject" else 0),
            timeouts=metrics.timeouts + (1 if outcome == "timeout" else 0),
            avg_slippage_bps=(
                _running_average(metrics.avg_slippage_bps, metrics.slippage_sample_count, max(slippage_bps or 0.0, 0.0))
                if slippage_bps is not None
                else metrics.avg_slippage_bps
            ),
            avg_fill_ratio=_running_average(
                metrics.avg_fill_ratio,
                metrics.fill_ratio_sample_count,
                max(min(fill_ratio, 1.0), 0.0),
            ),
            avg_realized_edge_bps=(
                _running_average(
                    metrics.avg_realized_edge_bps,
                    metrics.realized_edge_sample_count,
                    realized_edge_bps,
                )
                if realized_edge_bps is not None
                else metrics.avg_realized_edge_bps
            ),
            last_updated_time=(timestamp or _utc_now()).isoformat(),
            slippage_sample_count=metrics.slippage_sample_count + (1 if slippage_bps is not None else 0),
            fill_ratio_sample_count=metrics.fill_ratio_sample_count + 1,
            realized_edge_sample_count=metrics.realized_edge_sample_count + (1 if realized_edge_bps is not None else 0),
        )
        self._symbols[symbol] = updated
        self._persist()
        return updated

    def snapshot(self) -> dict[str, object]:
        return {
            "updated_at": _utc_now().isoformat(),
            "minimum_sample_size": MIN_EXECUTION_QUALITY_SAMPLE_SIZE,
            "symbols": {
                symbol: metrics.as_dict()
                for symbol, metrics in sorted(self._symbols.items())
            },
            "active_overlays": {
                symbol: overlay.as_dict()
                for symbol, overlay in sorted(
                    (
                        (symbol, self.overlay_for(symbol))
                        for symbol in self._symbols
                    ),
                    key=lambda item: item[0],
                )
                if overlay.sample_size >= MIN_EXECUTION_QUALITY_SAMPLE_SIZE
            },
        }
