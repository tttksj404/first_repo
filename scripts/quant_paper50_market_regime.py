#!/usr/bin/env python3
"""Build a read-only market regime snapshot for paper50 tuning gates.

The report uses Binance USD-M public 24h ticker data only. It never calls
private endpoints and never places, tests, cancels, or modifies orders.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = Path("quant_runtime_paper50/artifacts/paper50_market_regime_latest.json")
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "DOGEUSDT", "SOLUSDT", "1000PEPEUSDT", "XRPUSDT")
SYMBOL_ALIASES = {"1000PEPEUSDT": "PEPEUSDT"}
CORE_SYMBOLS = ("BTCUSDT", "ETHUSDT")
ALT_SYMBOLS = ("DOGEUSDT", "SOLUSDT", "PEPEUSDT", "XRPUSDT")
BASE_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _fetch_24h(symbol: str, *, timeout: float) -> tuple[dict[str, Any] | None, str | None]:
    query = urllib.parse.urlencode({"symbol": symbol})
    request = urllib.request.Request(f"{BASE_URL}?{query}", headers={"User-Agent": "paper50-regime/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(payload, dict):
        return None, "unexpected_payload"
    return payload, None


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def build_regime(rows: list[dict[str, Any]], errors: dict[str, str] | None = None) -> dict[str, Any]:
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        raw_symbol = str(row.get("symbol") or "").upper()
        symbol = SYMBOL_ALIASES.get(raw_symbol, raw_symbol)
        pct = _safe_float(row.get("priceChangePercent"))
        by_symbol[symbol] = {
            "source_symbol": raw_symbol,
            "price_change_pct_24h": pct,
            "last_price": _safe_float(row.get("lastPrice")),
            "quote_volume": _safe_float(row.get("quoteVolume")),
            "trade_count": int(_safe_float(row.get("count"))),
        }

    core_values = [by_symbol[symbol]["price_change_pct_24h"] for symbol in CORE_SYMBOLS if symbol in by_symbol]
    alt_values = [by_symbol[symbol]["price_change_pct_24h"] for symbol in ALT_SYMBOLS if symbol in by_symbol]
    core_avg = _avg(core_values)
    alt_avg = _avg(alt_values)
    alt_positive_count = sum(1 for symbol in ALT_SYMBOLS if by_symbol.get(symbol, {}).get("price_change_pct_24h", 0.0) > 0.25)
    alt_relative = round((alt_avg or 0.0) - (core_avg or 0.0), 6) if core_avg is not None and alt_avg is not None else None

    posture = "mixed"
    if core_avg is not None and alt_avg is not None:
        if core_avg <= -1.25 and alt_positive_count <= 1:
            posture = "broad_risk_off"
        elif core_avg >= -0.75 and alt_avg >= 0.25 and alt_positive_count >= 2 and (alt_relative or 0.0) >= 0.35:
            posture = "alt_relative_long_ok"

    symbol_gates: dict[str, dict[str, Any]] = {}
    for symbol in sorted(set(ALT_SYMBOLS).intersection(by_symbol)):
        pct = by_symbol[symbol]["price_change_pct_24h"]
        relative_to_core = round(pct - (core_avg or 0.0), 6) if core_avg is not None else None
        long_relax_allowed = posture == "alt_relative_long_ok" and pct > 0.0 and (relative_to_core or 0.0) >= 0.35
        symbol_gates[symbol] = {
            "long_relax_allowed": long_relax_allowed,
            "short_relax_allowed": posture == "broad_risk_off" and pct < -0.5,
            "relative_to_core_pct": relative_to_core,
            "price_change_pct_24h": pct,
            "reason": (
                "alt_outperforming_core_in_constructive_regime"
                if long_relax_allowed
                else "market_regime_not_supportive_for_long_relaxation"
            ),
        }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "paper50_market_regime",
        "paper_only": True,
        "source": "binance_usdm_24h_ticker",
        "errors": errors or {},
        "posture": posture,
        "core_avg_change_pct_24h": core_avg,
        "alt_avg_change_pct_24h": alt_avg,
        "alt_relative_to_core_pct": alt_relative,
        "alt_positive_count": alt_positive_count,
        "symbols": by_symbol,
        "symbol_gates": symbol_gates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for symbol in args.symbols or list(DEFAULT_SYMBOLS):
        payload, error = _fetch_24h(symbol, timeout=max(args.timeout, 1.0))
        if error:
            errors[symbol] = error
            continue
        if payload is not None:
            rows.append(payload)
    report = build_regime(rows, errors=errors)
    _write_json(Path(args.output), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
