from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any


@dataclass(frozen=True)
class SymbolCostCalibration:
    symbol: str
    empirical_fee_bps: float = 0.0
    empirical_entry_slippage_bps: float = 0.0
    empirical_exit_slippage_bps: float = 0.0
    fee_sample_count: int = 0
    slippage_sample_count: int = 0


@dataclass(frozen=True)
class CostCalibration:
    generated_at: str
    lookback_hours: int
    global_empirical_fee_bps: float = 0.0
    global_empirical_entry_slippage_bps: float = 0.0
    global_empirical_exit_slippage_bps: float = 0.0
    symbol_calibrations: tuple[SymbolCostCalibration, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def for_symbol(self, symbol: str) -> SymbolCostCalibration:
        for item in self.symbol_calibrations:
            if item.symbol == symbol:
                return item
        return SymbolCostCalibration(
            symbol=symbol,
            empirical_fee_bps=self.global_empirical_fee_bps,
            empirical_entry_slippage_bps=self.global_empirical_entry_slippage_bps,
            empirical_exit_slippage_bps=self.global_empirical_exit_slippage_bps,
        )


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


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fee_bps_from_fill(fill: dict[str, Any]) -> float:
    quote_volume = abs(_safe_float(fill.get("quoteVolume")))
    if quote_volume <= 0.0:
        return 0.0
    total_fee = 0.0
    fee_detail = fill.get("feeDetail")
    if isinstance(fee_detail, list):
        for item in fee_detail:
            if not isinstance(item, dict):
                continue
            total_fee += abs(_safe_float(item.get("totalFee")))
    if total_fee <= 0.0:
        return 0.0
    return (total_fee / quote_volume) * 10000.0


def _collect_live_order_references(*, base_dir: Path, lookback_hours: int) -> dict[str, dict[str, float | str]]:
    mode_root = base_dir / "output" / "paper-live-shell"
    if not mode_root.exists():
        return {}
    threshold = datetime.now(UTC) - timedelta(hours=lookback_hours)
    refs: dict[str, dict[str, float | str]] = {}
    for run_dir in mode_root.iterdir():
        if not run_dir.is_dir() or run_dir.name == "latest":
            continue
        modified = datetime.fromtimestamp(run_dir.stat().st_mtime, tz=UTC)
        if modified < threshold:
            continue
        for row in _load_jsonl(run_dir / "logs" / "live_orders.jsonl"):
            order_id = str(row.get("order_id") or "").strip()
            if not order_id:
                response = row.get("response")
                if isinstance(response, dict):
                    order_id = str(response.get("orderId") or "").strip()
            if not order_id:
                continue
            refs[order_id] = {
                "symbol": str(row.get("symbol") or ""),
                "reference_price": _safe_float(row.get("reference_price")),
            }
    return refs


def build_cost_calibration(
    *,
    fill_rows: list[dict[str, Any]],
    order_refs: dict[str, dict[str, float | str]] | None = None,
    lookback_hours: int = 72,
) -> CostCalibration:
    fee_samples_by_symbol: dict[str, list[float]] = {}
    slip_samples_by_symbol: dict[str, list[float]] = {}
    global_fee_samples: list[float] = []
    global_slip_samples: list[float] = []
    refs = order_refs or {}

    for row in fill_rows:
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        fee_bps = _fee_bps_from_fill(row)
        if fee_bps > 0.0:
            fee_samples_by_symbol.setdefault(symbol, []).append(fee_bps)
            global_fee_samples.append(fee_bps)
        order_id = str(row.get("orderId") or "").strip()
        reference = refs.get(order_id) if order_id else None
        if reference is None:
            continue
        fill_price = _safe_float(row.get("price"))
        reference_price = _safe_float(reference.get("reference_price"))
        if fill_price <= 0.0 or reference_price <= 0.0:
            continue
        slippage_bps = abs(fill_price - reference_price) / reference_price * 10000.0
        slip_samples_by_symbol.setdefault(symbol, []).append(slippage_bps)
        global_slip_samples.append(slippage_bps)

    symbols = sorted(set(fee_samples_by_symbol) | set(slip_samples_by_symbol))
    symbol_calibrations = tuple(
        SymbolCostCalibration(
            symbol=symbol,
            empirical_fee_bps=round(median(fee_samples_by_symbol.get(symbol, [0.0])), 6),
            empirical_entry_slippage_bps=round(median(slip_samples_by_symbol.get(symbol, [0.0])), 6),
            empirical_exit_slippage_bps=round(median(slip_samples_by_symbol.get(symbol, [0.0])), 6),
            fee_sample_count=len(fee_samples_by_symbol.get(symbol, [])),
            slippage_sample_count=len(slip_samples_by_symbol.get(symbol, [])),
        )
        for symbol in symbols
    )
    return CostCalibration(
        generated_at=datetime.now(UTC).isoformat(),
        lookback_hours=lookback_hours,
        global_empirical_fee_bps=round(median(global_fee_samples), 6) if global_fee_samples else 0.0,
        global_empirical_entry_slippage_bps=round(median(global_slip_samples), 6) if global_slip_samples else 0.0,
        global_empirical_exit_slippage_bps=round(median(global_slip_samples), 6) if global_slip_samples else 0.0,
        symbol_calibrations=symbol_calibrations,
    )


def load_cost_calibration(path: str | Path) -> CostCalibration | None:
    target = Path(path)
    if not target.exists():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    rows = tuple(SymbolCostCalibration(**item) for item in payload.get("symbol_calibrations", ()))
    return CostCalibration(
        generated_at=str(payload.get("generated_at") or ""),
        lookback_hours=int(payload.get("lookback_hours") or 72),
        global_empirical_fee_bps=_safe_float(payload.get("global_empirical_fee_bps")),
        global_empirical_entry_slippage_bps=_safe_float(payload.get("global_empirical_entry_slippage_bps")),
        global_empirical_exit_slippage_bps=_safe_float(payload.get("global_empirical_exit_slippage_bps")),
        symbol_calibrations=rows,
    )


def write_cost_calibration(*, calibration: CostCalibration, output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(calibration.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return target


def refresh_bitget_cost_calibration(
    *,
    rest_client: Any,
    base_dir: str | Path = "quant_runtime",
    output_path: str | Path | None = None,
    lookback_hours: int = 72,
    limit: int = 200,
) -> Path:
    root = Path(base_dir)
    refs = _collect_live_order_references(base_dir=root, lookback_hours=lookback_hours)
    fills_payload = rest_client.get_futures_fill_history(limit=limit, max_pages=1)
    calibration = build_cost_calibration(
        fill_rows=list(fills_payload.get("fills", [])),
        order_refs=refs,
        lookback_hours=lookback_hours,
    )
    target = Path(output_path) if output_path is not None else root / "artifacts" / "cost_calibration.json"
    return write_cost_calibration(calibration=calibration, output_path=target)
