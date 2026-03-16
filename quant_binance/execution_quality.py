from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from quant_binance.models import DecisionIntent


MIN_EXECUTION_QUALITY_SAMPLE_SIZE = 3
EXECUTION_QUALITY_DECAY_HALF_LIFE_DAYS = 14.0
EXECUTION_QUALITY_DECAY_HALF_LIFE_SECONDS = EXECUTION_QUALITY_DECAY_HALF_LIFE_DAYS * 24.0 * 60.0 * 60.0


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


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _safe_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decay_factor(last_updated_time: str, now: datetime) -> float:
    previous = _safe_datetime(last_updated_time)
    if previous is None:
        return 1.0
    elapsed_seconds = max((now - previous).total_seconds(), 0.0)
    if elapsed_seconds <= 0.0:
        return 1.0
    return math.exp(-math.log(2.0) * elapsed_seconds / EXECUTION_QUALITY_DECAY_HALF_LIFE_SECONDS)


def _quality_scale(value: float, *, start: float, span: float, cap: float) -> float:
    if span <= 0.0:
        return 0.0
    return _clamp((value - start) / span, 0.0, 1.0) * cap


def _normalize_scope_value(value: str | None) -> str:
    return str(value or "").strip().lower()


def _context_key(symbol: str, *, market: str | None = None, exchange_id: str | None = None) -> str | None:
    normalized_market = _normalize_scope_value(market)
    normalized_exchange = _normalize_scope_value(exchange_id)
    if not normalized_market and not normalized_exchange:
        return None
    parts = [symbol]
    if normalized_market:
        parts.append(f"market={normalized_market}")
    if normalized_exchange:
        parts.append(f"exchange={normalized_exchange}")
    return "|".join(parts)


def _context_key_details(key: str) -> dict[str, str]:
    symbol, *_ = key.split("|")
    details = {"symbol": symbol, "market": "", "exchange_id": ""}
    for part in key.split("|")[1:]:
        name, _, value = part.partition("=")
        if name == "market":
            details["market"] = value
        if name == "exchange":
            details["exchange_id"] = value
    return details


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
    weighted_attempts: float = 0.0
    weighted_fills: float = 0.0
    weighted_partial_fills: float = 0.0
    weighted_rejects: float = 0.0
    weighted_timeouts: float = 0.0
    weighted_slippage_sum: float = 0.0
    weighted_fill_ratio_sum: float = 0.0
    weighted_realized_edge_sum: float = 0.0
    weighted_slippage_samples: float = 0.0
    weighted_fill_ratio_samples: float = 0.0
    weighted_realized_edge_samples: float = 0.0

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
            weighted_attempts=_safe_float(payload.get("weighted_attempts")),
            weighted_fills=_safe_float(payload.get("weighted_fills")),
            weighted_partial_fills=_safe_float(payload.get("weighted_partial_fills")),
            weighted_rejects=_safe_float(payload.get("weighted_rejects")),
            weighted_timeouts=_safe_float(payload.get("weighted_timeouts")),
            weighted_slippage_sum=_safe_float(payload.get("weighted_slippage_sum")),
            weighted_fill_ratio_sum=_safe_float(payload.get("weighted_fill_ratio_sum")),
            weighted_realized_edge_sum=_safe_float(payload.get("weighted_realized_edge_sum")),
            weighted_slippage_samples=_safe_float(payload.get("weighted_slippage_samples")),
            weighted_fill_ratio_samples=_safe_float(payload.get("weighted_fill_ratio_samples")),
            weighted_realized_edge_samples=_safe_float(payload.get("weighted_realized_edge_samples")),
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
            "weighted_attempts": round(self.weighted_attempts, 6),
            "weighted_fills": round(self.weighted_fills, 6),
            "weighted_partial_fills": round(self.weighted_partial_fills, 6),
            "weighted_rejects": round(self.weighted_rejects, 6),
            "weighted_timeouts": round(self.weighted_timeouts, 6),
            "weighted_slippage_sum": round(self.weighted_slippage_sum, 6),
            "weighted_fill_ratio_sum": round(self.weighted_fill_ratio_sum, 6),
            "weighted_realized_edge_sum": round(self.weighted_realized_edge_sum, 6),
            "weighted_slippage_samples": round(self.weighted_slippage_samples, 6),
            "weighted_fill_ratio_samples": round(self.weighted_fill_ratio_samples, 6),
            "weighted_realized_edge_samples": round(self.weighted_realized_edge_samples, 6),
        }


@dataclass(frozen=True)
class EffectiveExecutionQualityMetrics:
    effective_sample_size: float = 0.0
    avg_slippage_bps: float = 0.0
    avg_fill_ratio: float = 1.0
    avg_realized_edge_bps: float = 0.0
    reject_rate: float = 0.0
    timeout_rate: float = 0.0
    partial_fill_rate: float = 0.0


@dataclass(frozen=True)
class ExecutionQualityOverlay:
    sample_size: int = 0
    raw_sample_size: int = 0
    effective_sample_size: float = 0.0
    size_multiplier: float = 1.0
    edge_penalty_bps: float = 0.0
    trade_restraint: str = "none"
    avg_slippage_bps: float = 0.0
    avg_fill_ratio: float = 1.0
    avg_realized_edge_bps: float = 0.0
    reject_rate: float = 0.0
    timeout_rate: float = 0.0
    partial_fill_rate: float = 0.0
    scope_key: str = ""
    symbol: str = ""
    market: str = ""
    exchange_id: str = ""
    source: str = "symbol"
    degraded: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "sample_size": self.sample_size,
            "raw_sample_size": self.raw_sample_size,
            "effective_sample_size": round(self.effective_sample_size, 6),
            "size_multiplier": round(self.size_multiplier, 6),
            "edge_penalty_bps": round(self.edge_penalty_bps, 6),
            "trade_restraint": self.trade_restraint,
            "avg_slippage_bps": round(self.avg_slippage_bps, 6),
            "avg_fill_ratio": round(self.avg_fill_ratio, 6),
            "avg_realized_edge_bps": round(self.avg_realized_edge_bps, 6),
            "reject_rate": round(self.reject_rate, 6),
            "timeout_rate": round(self.timeout_rate, 6),
            "partial_fill_rate": round(self.partial_fill_rate, 6),
            "scope_key": self.scope_key,
            "symbol": self.symbol,
            "market": self.market,
            "exchange_id": self.exchange_id,
            "source": self.source,
            "degraded": self.degraded,
        }


class ExecutionQualityState:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._symbols: dict[str, ExecutionQualityMetrics] = {}
        self._contexts: dict[str, ExecutionQualityMetrics] = {}
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
        if isinstance(symbols, dict):
            for symbol, raw_metrics in symbols.items():
                self._symbols[str(symbol)] = ExecutionQualityMetrics.from_dict(
                    raw_metrics if isinstance(raw_metrics, dict) else None
                )
        contexts = payload.get("contexts")
        if not isinstance(contexts, dict):
            return
        for key, raw_context in contexts.items():
            if not isinstance(raw_context, dict):
                continue
            metrics_payload = raw_context.get("metrics")
            if isinstance(metrics_payload, dict):
                self._contexts[str(key)] = ExecutionQualityMetrics.from_dict(metrics_payload)
                continue
            self._contexts[str(key)] = ExecutionQualityMetrics.from_dict(raw_context)

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.snapshot()
        with NamedTemporaryFile("w", delete=False, dir=str(self.path.parent), encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            temp_path = Path(handle.name)
        temp_path.replace(self.path)

    def _hydrate_weighted_metrics(self, metrics: ExecutionQualityMetrics) -> ExecutionQualityMetrics:
        if metrics.weighted_attempts > 0.0 or metrics.attempts <= 0:
            return metrics
        return replace(
            metrics,
            weighted_attempts=float(metrics.attempts),
            weighted_fills=float(metrics.fills),
            weighted_partial_fills=float(metrics.partial_fills),
            weighted_rejects=float(metrics.rejects),
            weighted_timeouts=float(metrics.timeouts),
            weighted_slippage_sum=float(metrics.avg_slippage_bps * metrics.slippage_sample_count),
            weighted_fill_ratio_sum=float(metrics.avg_fill_ratio * metrics.fill_ratio_sample_count),
            weighted_realized_edge_sum=float(metrics.avg_realized_edge_bps * metrics.realized_edge_sample_count),
            weighted_slippage_samples=float(metrics.slippage_sample_count),
            weighted_fill_ratio_samples=float(metrics.fill_ratio_sample_count),
            weighted_realized_edge_samples=float(metrics.realized_edge_sample_count),
        )

    def _decayed_metrics(
        self,
        metrics: ExecutionQualityMetrics,
        *,
        now: datetime,
    ) -> ExecutionQualityMetrics:
        hydrated = self._hydrate_weighted_metrics(metrics)
        factor = _decay_factor(hydrated.last_updated_time, now)
        if factor >= 0.999999:
            return hydrated
        return replace(
            hydrated,
            weighted_attempts=hydrated.weighted_attempts * factor,
            weighted_fills=hydrated.weighted_fills * factor,
            weighted_partial_fills=hydrated.weighted_partial_fills * factor,
            weighted_rejects=hydrated.weighted_rejects * factor,
            weighted_timeouts=hydrated.weighted_timeouts * factor,
            weighted_slippage_sum=hydrated.weighted_slippage_sum * factor,
            weighted_fill_ratio_sum=hydrated.weighted_fill_ratio_sum * factor,
            weighted_realized_edge_sum=hydrated.weighted_realized_edge_sum * factor,
            weighted_slippage_samples=hydrated.weighted_slippage_samples * factor,
            weighted_fill_ratio_samples=hydrated.weighted_fill_ratio_samples * factor,
            weighted_realized_edge_samples=hydrated.weighted_realized_edge_samples * factor,
        )

    def _effective_metrics(
        self,
        metrics: ExecutionQualityMetrics,
        *,
        now: datetime,
    ) -> EffectiveExecutionQualityMetrics:
        decayed = self._decayed_metrics(metrics, now=now)
        attempts = max(decayed.weighted_attempts, 0.0)
        slippage_samples = max(decayed.weighted_slippage_samples, 0.0)
        fill_ratio_samples = max(decayed.weighted_fill_ratio_samples, 0.0)
        realized_edge_samples = max(decayed.weighted_realized_edge_samples, 0.0)
        return EffectiveExecutionQualityMetrics(
            effective_sample_size=attempts,
            avg_slippage_bps=(
                decayed.weighted_slippage_sum / slippage_samples
                if slippage_samples > 0.0
                else metrics.avg_slippage_bps
            ),
            avg_fill_ratio=(
                decayed.weighted_fill_ratio_sum / fill_ratio_samples
                if fill_ratio_samples > 0.0
                else metrics.avg_fill_ratio
            ),
            avg_realized_edge_bps=(
                decayed.weighted_realized_edge_sum / realized_edge_samples
                if realized_edge_samples > 0.0
                else metrics.avg_realized_edge_bps
            ),
            reject_rate=decayed.weighted_rejects / attempts if attempts > 0.0 else 0.0,
            timeout_rate=decayed.weighted_timeouts / attempts if attempts > 0.0 else 0.0,
            partial_fill_rate=decayed.weighted_partial_fills / attempts if attempts > 0.0 else 0.0,
        )

    def _context_metrics_for(
        self,
        symbol: str,
        *,
        market: str | None = None,
        exchange_id: str | None = None,
    ) -> tuple[str | None, ExecutionQualityMetrics | None]:
        key = _context_key(symbol, market=market, exchange_id=exchange_id)
        if key is None:
            return None, None
        return key, self._contexts.get(key)

    def _has_context_for_symbol(self, symbol: str) -> bool:
        prefix = f"{symbol}|"
        return any(key == symbol or key.startswith(prefix) for key in self._contexts)

    def _overlay_from_metrics(
        self,
        *,
        metrics: ExecutionQualityMetrics,
        symbol: str,
        scope_key: str,
        market: str = "",
        exchange_id: str = "",
        source: str,
        now: datetime,
    ) -> ExecutionQualityOverlay:
        effective = self._effective_metrics(metrics, now=now)
        effective_attempts = max(effective.effective_sample_size, 0.0)
        rounded_sample_size = max(int(effective_attempts + 0.5), 0)
        if rounded_sample_size < MIN_EXECUTION_QUALITY_SAMPLE_SIZE:
            return ExecutionQualityOverlay(
                sample_size=rounded_sample_size,
                raw_sample_size=max(metrics.attempts, 0),
                effective_sample_size=effective_attempts,
                avg_slippage_bps=effective.avg_slippage_bps,
                avg_fill_ratio=effective.avg_fill_ratio,
                avg_realized_edge_bps=effective.avg_realized_edge_bps,
                reject_rate=effective.reject_rate,
                timeout_rate=effective.timeout_rate,
                partial_fill_rate=effective.partial_fill_rate,
                scope_key=scope_key,
                symbol=symbol,
                market=market,
                exchange_id=exchange_id,
                source=source,
            )

        reject_timeout_rate = effective.reject_rate + effective.timeout_rate
        fill_ratio_gap = max(1.0 - effective.avg_fill_ratio, 0.0)
        negative_edge_bps = max(-effective.avg_realized_edge_bps, 0.0)

        size_reduction = 0.0
        size_reduction += _quality_scale(reject_timeout_rate, start=0.12, span=0.48, cap=0.40)
        size_reduction += _quality_scale(fill_ratio_gap, start=0.08, span=0.57, cap=0.28)
        size_reduction += _quality_scale(effective.partial_fill_rate, start=0.18, span=0.42, cap=0.18)
        size_reduction += _quality_scale(effective.avg_slippage_bps, start=5.0, span=15.0, cap=0.22)
        size_reduction += _quality_scale(negative_edge_bps, start=0.5, span=5.5, cap=0.15)
        size_multiplier = _clamp(1.0 - size_reduction, 0.0, 1.0)
        if effective.avg_fill_ratio < 0.85 or effective.partial_fill_rate >= 0.35:
            size_multiplier = min(size_multiplier, 0.8)
        if effective.avg_slippage_bps > 8.0:
            size_multiplier = min(size_multiplier, 0.85)
        if (
            effective.avg_slippage_bps > 12.0
            or effective.avg_fill_ratio < 0.65
            or effective.partial_fill_rate >= 0.5
        ):
            size_multiplier = min(size_multiplier, 0.6)

        edge_penalty_bps = 0.0
        edge_penalty_bps += _quality_scale(reject_timeout_rate, start=0.1, span=0.5, cap=6.0)
        edge_penalty_bps += _quality_scale(effective.avg_slippage_bps, start=6.0, span=14.0, cap=2.0)
        edge_penalty_bps += _quality_scale(fill_ratio_gap, start=0.08, span=0.57, cap=1.5)
        if reject_timeout_rate >= 0.2:
            edge_penalty_bps = max(edge_penalty_bps, 2.0)
        if reject_timeout_rate >= 0.35:
            edge_penalty_bps = max(edge_penalty_bps, 4.0)
        if reject_timeout_rate >= 0.5:
            edge_penalty_bps = max(edge_penalty_bps, 6.0)
        if effective.avg_realized_edge_bps < 0.0:
            edge_penalty_bps = max(edge_penalty_bps, min(abs(effective.avg_realized_edge_bps), 4.0))
        edge_penalty_bps = round(min(edge_penalty_bps, 8.0), 6)

        trade_restraint = "none"
        if (
            reject_timeout_rate >= 0.6
            or effective.avg_fill_ratio < 0.35
            or effective.avg_slippage_bps > 20.0
            or (effective_attempts >= 5.0 and effective.avg_realized_edge_bps < -2.0)
        ):
            trade_restraint = "execution_quality_halt"
            size_multiplier = 0.0

        degraded = (
            trade_restraint != "none"
            or size_multiplier < 0.999999
            or edge_penalty_bps > 0.0
        )
        return ExecutionQualityOverlay(
            sample_size=rounded_sample_size,
            raw_sample_size=max(metrics.attempts, 0),
            effective_sample_size=effective_attempts,
            size_multiplier=round(size_multiplier, 6),
            edge_penalty_bps=edge_penalty_bps,
            trade_restraint=trade_restraint,
            avg_slippage_bps=effective.avg_slippage_bps,
            avg_fill_ratio=effective.avg_fill_ratio,
            avg_realized_edge_bps=effective.avg_realized_edge_bps,
            reject_rate=effective.reject_rate,
            timeout_rate=effective.timeout_rate,
            partial_fill_rate=effective.partial_fill_rate,
            scope_key=scope_key,
            symbol=symbol,
            market=market,
            exchange_id=exchange_id,
            source=source,
            degraded=degraded,
        )

    def metrics_for(self, symbol: str) -> ExecutionQualityMetrics:
        return self._symbols.get(symbol, ExecutionQualityMetrics())

    def overlay_for(
        self,
        symbol: str,
        *,
        market: str | None = None,
        exchange_id: str | None = None,
        now: datetime | None = None,
    ) -> ExecutionQualityOverlay:
        current_time = now or _utc_now()
        normalized_market = _normalize_scope_value(market)
        normalized_exchange = _normalize_scope_value(exchange_id)
        key, context_metrics = self._context_metrics_for(
            symbol,
            market=normalized_market,
            exchange_id=normalized_exchange,
        )
        if key is not None and context_metrics is not None:
            return self._overlay_from_metrics(
                metrics=context_metrics,
                symbol=symbol,
                scope_key=key,
                market=normalized_market,
                exchange_id=normalized_exchange,
                source="context",
                now=current_time,
            )
        if key is not None and self._has_context_for_symbol(symbol):
            return ExecutionQualityOverlay(
                scope_key=key,
                symbol=symbol,
                market=normalized_market,
                exchange_id=normalized_exchange,
                source="context",
            )
        return self._overlay_from_metrics(
            metrics=self.metrics_for(symbol),
            symbol=symbol,
            scope_key=symbol,
            source="symbol",
            now=current_time,
        )

    def apply_overlay(
        self,
        decision: DecisionIntent,
        *,
        exchange_id: str | None = None,
        now: datetime | None = None,
    ) -> DecisionIntent:
        overlay = self.overlay_for(
            decision.symbol,
            market=decision.final_mode,
            exchange_id=exchange_id,
            now=now,
        )
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

    def _record_metrics(
        self,
        metrics: ExecutionQualityMetrics,
        *,
        outcome: str,
        fill_ratio: float,
        slippage_bps: float | None,
        realized_edge_bps: float | None,
        timestamp: datetime,
    ) -> ExecutionQualityMetrics:
        normalized_fill_ratio = _clamp(fill_ratio, 0.0, 1.0)
        normalized_slippage_bps = max(slippage_bps or 0.0, 0.0)
        decayed = self._decayed_metrics(metrics, now=timestamp)
        return ExecutionQualityMetrics(
            attempts=metrics.attempts + 1,
            fills=metrics.fills + (1 if outcome == "filled" else 0),
            partial_fills=metrics.partial_fills + (1 if outcome == "partial_fill" else 0),
            rejects=metrics.rejects + (1 if outcome == "reject" else 0),
            timeouts=metrics.timeouts + (1 if outcome == "timeout" else 0),
            avg_slippage_bps=(
                _running_average(metrics.avg_slippage_bps, metrics.slippage_sample_count, normalized_slippage_bps)
                if slippage_bps is not None
                else metrics.avg_slippage_bps
            ),
            avg_fill_ratio=_running_average(
                metrics.avg_fill_ratio,
                metrics.fill_ratio_sample_count,
                normalized_fill_ratio,
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
            last_updated_time=timestamp.isoformat(),
            slippage_sample_count=metrics.slippage_sample_count + (1 if slippage_bps is not None else 0),
            fill_ratio_sample_count=metrics.fill_ratio_sample_count + 1,
            realized_edge_sample_count=metrics.realized_edge_sample_count + (1 if realized_edge_bps is not None else 0),
            weighted_attempts=decayed.weighted_attempts + 1.0,
            weighted_fills=decayed.weighted_fills + (1.0 if outcome == "filled" else 0.0),
            weighted_partial_fills=decayed.weighted_partial_fills + (1.0 if outcome == "partial_fill" else 0.0),
            weighted_rejects=decayed.weighted_rejects + (1.0 if outcome == "reject" else 0.0),
            weighted_timeouts=decayed.weighted_timeouts + (1.0 if outcome == "timeout" else 0.0),
            weighted_slippage_sum=(
                decayed.weighted_slippage_sum + normalized_slippage_bps
                if slippage_bps is not None
                else decayed.weighted_slippage_sum
            ),
            weighted_fill_ratio_sum=decayed.weighted_fill_ratio_sum + normalized_fill_ratio,
            weighted_realized_edge_sum=(
                decayed.weighted_realized_edge_sum + float(realized_edge_bps)
                if realized_edge_bps is not None
                else decayed.weighted_realized_edge_sum
            ),
            weighted_slippage_samples=decayed.weighted_slippage_samples + (1.0 if slippage_bps is not None else 0.0),
            weighted_fill_ratio_samples=decayed.weighted_fill_ratio_samples + 1.0,
            weighted_realized_edge_samples=(
                decayed.weighted_realized_edge_samples + (1.0 if realized_edge_bps is not None else 0.0)
            ),
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
        market: str | None = None,
        exchange_id: str | None = None,
    ) -> ExecutionQualityMetrics:
        event_time = timestamp or _utc_now()
        symbol_metrics = self.metrics_for(symbol)
        updated_symbol_metrics = self._record_metrics(
            symbol_metrics,
            outcome=outcome,
            fill_ratio=fill_ratio,
            slippage_bps=slippage_bps,
            realized_edge_bps=realized_edge_bps,
            timestamp=event_time,
        )
        self._symbols[symbol] = updated_symbol_metrics
        key = _context_key(symbol, market=market, exchange_id=exchange_id)
        if key is not None:
            context_metrics = self._contexts.get(key, ExecutionQualityMetrics())
            self._contexts[key] = self._record_metrics(
                context_metrics,
                outcome=outcome,
                fill_ratio=fill_ratio,
                slippage_bps=slippage_bps,
                realized_edge_bps=realized_edge_bps,
                timestamp=event_time,
            )
        self._persist()
        return updated_symbol_metrics

    def snapshot(self) -> dict[str, object]:
        current_time = _utc_now()
        overlays: dict[str, ExecutionQualityOverlay] = {
            symbol: self._overlay_from_metrics(
                metrics=metrics,
                symbol=symbol,
                scope_key=symbol,
                source="symbol",
                now=current_time,
            )
            for symbol, metrics in sorted(self._symbols.items())
        }
        for key, metrics in sorted(self._contexts.items()):
            details = _context_key_details(key)
            overlays[key] = self._overlay_from_metrics(
                metrics=metrics,
                symbol=details["symbol"],
                scope_key=key,
                market=details["market"],
                exchange_id=details["exchange_id"],
                source="context",
                now=current_time,
            )
        active_overlays = {
            key: overlay.as_dict()
            for key, overlay in overlays.items()
            if overlay.sample_size >= MIN_EXECUTION_QUALITY_SAMPLE_SIZE
        }
        degraded_keys = sorted(
            key
            for key, overlay in overlays.items()
            if overlay.degraded and overlay.sample_size >= MIN_EXECUTION_QUALITY_SAMPLE_SIZE
        )
        return {
            "updated_at": current_time.isoformat(),
            "minimum_sample_size": MIN_EXECUTION_QUALITY_SAMPLE_SIZE,
            "decay_half_life_days": EXECUTION_QUALITY_DECAY_HALF_LIFE_DAYS,
            "symbols": {
                symbol: metrics.as_dict()
                for symbol, metrics in sorted(self._symbols.items())
            },
            "contexts": {
                key: {
                    **_context_key_details(key),
                    "metrics": metrics.as_dict(),
                }
                for key, metrics in sorted(self._contexts.items())
            },
            "active_overlays": active_overlays,
            "degraded_keys": degraded_keys,
            "degraded_overlays": {
                key: active_overlays[key]
                for key in degraded_keys
            },
        }
