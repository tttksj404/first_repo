#!/usr/bin/env python3
"""Build a Bitget-specific paper-only entry overlay and tune it per symbol.

This script never places, tests, cancels, or modifies exchange orders. It uses
public Bitget market data plus local paper/counterfactual artifacts, then writes
a paper-only strategy override candidate for forward testing.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_binance.bitget_entry_overlay import (  # noqa: E402
    DEFAULT_BITGET_SYMBOLS,
    BitgetMarketMetrics,
    apply_tuned_profiles,
    effective_round_trip_cost_bps,
    safe_float,
    tune_symbol_profile,
)
from quant_binance.execution.client_factory import build_exchange_rest_client  # noqa: E402


DEFAULT_OUTPUT_BASE = Path("quant_runtime_paper50")
DEFAULT_FILTERS = DEFAULT_OUTPUT_BASE / "paper50_multi_symbol_filters.json"
DEFAULT_COUNTERFACTUAL = DEFAULT_OUTPUT_BASE / "artifacts" / "paper50_counterfactual_latest.json"
DEFAULT_OUTPUT_DIR = DEFAULT_OUTPUT_BASE / "bitget_overlay_tuning"


def _read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ema(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    alpha = 2.0 / (window + 1.0)
    result = values[-window]
    for value in values[-window + 1 :]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def _market_trend_from_klines(klines: list[dict[str, Any]]) -> tuple[float, float]:
    rows = sorted(klines, key=lambda item: int(item.get("open_time") or 0))
    closes = [safe_float(row.get("close_price")) for row in rows if safe_float(row.get("close_price")) > 0.0]
    if len(closes) < 60:
        return 0.0, 0.0
    ema20 = _ema(closes, 20)
    ema60 = _ema(closes, 60)
    trend = 0.0 if not ema20 or not ema60 else (ema20 / ema60 - 1.0) * 10000.0
    returns = []
    for prev, cur in zip(closes, closes[1:]):
        if prev > 0.0 and cur > 0.0:
            returns.append((cur / prev - 1.0) * 10000.0)
    rv15 = statistics.pstdev(returns[-32:]) if len(returns) >= 32 else 0.0
    return round(trend, 6), round(rv15, 6)


def _fetch_taker_flow(client: Any, symbol: str, *, delay_seconds: float) -> tuple[float | None, float | None, str | None]:
    if delay_seconds > 0.0:
        time.sleep(delay_seconds)
    try:
        payload = client.send(
            client.build_public_request(
                path="/api/v2/mix/market/taker-buy-sell",
                params={"symbol": symbol, "period": "1h"},
            )
        )
    except (HTTPError, URLError, RuntimeError, TimeoutError) as exc:
        return None, None, f"{type(exc).__name__}: {str(exc)[:160]}"
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        return None, None, "unexpected_response_shape"
    last_rows = sorted(rows, key=lambda item: int(item.get("ts") or 0))[-6:]
    buy = sum(safe_float(item.get("buyVolume")) for item in last_rows)
    sell = sum(safe_float(item.get("sellVolume")) for item in last_rows)
    total = buy + sell
    if total <= 0.0:
        return None, None, "empty_taker_volume"
    return round(buy / total, 6), round(buy - sell, 6), None


def _fetch_metrics(client: Any, symbol: str, *, taker_delay_seconds: float) -> BitgetMarketMetrics:
    ticker = client.get_book_ticker(market="futures", symbol=symbol)
    mark = client.get_mark_price(symbol=symbol)
    raw = dict(ticker.get("raw") or {})
    last_price = safe_float(raw.get("lastPr") or mark.get("markPrice"))
    bid = safe_float(ticker.get("bidPrice"))
    ask = safe_float(ticker.get("askPrice"))
    spread_bps = 0.0 if min(last_price, bid, ask) <= 0.0 else (ask - bid) / last_price * 10000.0
    index_price = safe_float(mark.get("indexPrice"))
    mark_price = safe_float(mark.get("markPrice"))
    basis_bps = 0.0 if index_price <= 0.0 else (mark_price / index_price - 1.0) * 10000.0
    klines = client.get_klines(market="futures", symbol=symbol, interval="15m", limit=96)
    trend_bps, rv15_bps = _market_trend_from_klines(klines)
    taker_ratio, taker_net, taker_error = _fetch_taker_flow(client, symbol, delay_seconds=taker_delay_seconds)
    return BitgetMarketMetrics(
        symbol=symbol,
        last_price=last_price,
        quote_volume_24h=safe_float(raw.get("quoteVolume") or raw.get("usdtVolume")),
        change_24h_pct=safe_float(raw.get("change24h")) * 100.0,
        spread_bps=round(spread_bps, 6),
        funding_pct=safe_float(mark.get("lastFundingRate")) * 100.0,
        mark_basis_bps=round(basis_bps, 6),
        ema20_60_bps=trend_bps,
        rv15_bps=rv15_bps,
        taker_buy_ratio_6h=taker_ratio,
        taker_buy_minus_sell_6h=taker_net,
        taker_error=taker_error,
    )


def build_tuning_report(
    *,
    symbols: tuple[str, ...],
    filters: dict[str, Any],
    counterfactual: dict[str, Any],
    taker_delay_seconds: float,
    allow_insecure_ssl: bool,
) -> dict[str, Any]:
    client = build_exchange_rest_client(
        exchange="bitget",
        allow_insecure_ssl=allow_insecure_ssl,
        allow_missing_credentials=True,
    )
    profiles = dict(filters.get("symbol_filter_profiles") or {})
    cf_summaries = dict(counterfactual.get("symbol_summaries") or {})
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        metrics = _fetch_metrics(client, symbol, taker_delay_seconds=taker_delay_seconds)
        tuning = tune_symbol_profile(
            metrics=metrics,
            baseline_profile=dict(profiles.get(symbol) or {}),
            counterfactual_summary=dict(cf_summaries.get(symbol) or {}),
        )
        rows.append(
            {
                "symbol": symbol,
                "market_metrics": {
                    **metrics.__dict__,
                    "effective_round_trip_cost_bps": effective_round_trip_cost_bps(metrics),
                },
                "tuning": tuning,
            }
        )
    tuned_rows = [dict(row["tuning"]) for row in rows]
    tuned_filters = apply_tuned_profiles(filters, tuned_rows)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "exchange": "bitget",
        "product_type": "USDT-FUTURES",
        "paper_only": True,
        "live_orders": "disabled",
        "symbols": list(symbols),
        "rows": rows,
        "tuned_filters": tuned_filters,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Tune Bitget per-symbol entry overlay in paper-only mode.")
    parser.add_argument("--filters", default=str(DEFAULT_FILTERS))
    parser.add_argument("--counterfactual", default=str(DEFAULT_COUNTERFACTUAL))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--symbols", default=",".join(DEFAULT_BITGET_SYMBOLS))
    parser.add_argument("--taker-delay-seconds", type=float, default=1.05)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--interval-seconds", type=float, default=0.0)
    parser.add_argument("--insecure-ssl", action="store_true")
    args = parser.parse_args()

    symbols = tuple(symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip())
    output_dir = Path(args.output_dir)
    report_path = output_dir / "bitget_overlay_tuning_report.json"
    filters_path = output_dir / "paper50_multi_symbol_filters.bitget_tuned.json"
    latest_report_path = output_dir / "latest.json"

    filters = _read_json(Path(args.filters))
    counterfactual = _read_json(Path(args.counterfactual))
    iteration_reports: list[dict[str, Any]] = []
    iteration_count = max(int(args.iterations), 1)
    for iteration in range(iteration_count):
        report = build_tuning_report(
            symbols=symbols,
            filters=filters,
            counterfactual=counterfactual,
            taker_delay_seconds=args.taker_delay_seconds,
            allow_insecure_ssl=args.insecure_ssl,
        )
        report["iteration_index"] = iteration + 1
        iteration_reports.append(report)
        if iteration + 1 < iteration_count and args.interval_seconds > 0.0:
            time.sleep(args.interval_seconds)
    report = iteration_reports[-1]
    action_counts: dict[str, dict[str, int]] = {}
    for iteration_report in iteration_reports:
        for row in list(iteration_report.get("rows") or []):
            symbol = str(row.get("symbol") or "").upper()
            action = str(dict(row.get("tuning") or {}).get("action") or "unknown")
            action_counts.setdefault(symbol, {})
            action_counts[symbol][action] = action_counts[symbol].get(action, 0) + 1
    report["realtime_test"] = {
        "iteration_count": iteration_count,
        "interval_seconds": args.interval_seconds,
        "first_generated_at": iteration_reports[0].get("generated_at"),
        "last_generated_at": iteration_reports[-1].get("generated_at"),
        "action_counts": action_counts,
    }
    _write_json(report_path, report)
    _write_json(latest_report_path, report)
    _write_json(filters_path, dict(report["tuned_filters"]))
    print(json.dumps({"report": str(report_path), "tuned_filters": str(filters_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
