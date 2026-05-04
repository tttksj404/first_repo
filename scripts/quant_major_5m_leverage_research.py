#!/usr/bin/env python3
"""Paper-only 5m major-coin trend and leverage profile research.

This script fetches Binance USD-M public 5m candles for major symbols, builds a
simple multi-bar trend-following signal, and compares hold/leverage profiles.
It never calls private endpoints and never places, tests, cancels, or modifies
orders.
"""

from __future__ import annotations

import argparse
import json
import statistics
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = Path("quant_runtime_paper50/artifacts/major_5m_leverage_research_latest.json")
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
BASE_URL = "https://fapi.binance.com/fapi/v1/klines"
HOLD_BARS = (3, 6, 12, 36, 72)
LEVERAGES = (1, 2, 5)
ROUND_TRIP_COST_BPS = 8.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 6) if values else None


def _ret_bps(start: float, end: float) -> float:
    if start <= 0.0:
        return 0.0
    return ((end / start) - 1.0) * 10000.0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_kline(row: list[Any]) -> dict[str, Any] | None:
    if len(row) < 11:
        return None
    return {
        "open_time": int(_safe_float(row[0])),
        "open": _safe_float(row[1]),
        "high": _safe_float(row[2]),
        "low": _safe_float(row[3]),
        "close": _safe_float(row[4]),
        "volume": _safe_float(row[5]),
        "close_time": int(_safe_float(row[6])),
        "quote_volume": _safe_float(row[7]),
        "trade_count": int(_safe_float(row[8])),
    }


def fetch_klines(symbol: str, *, interval: str = "5m", limit: int = 1000, timeout: float = 12.0) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": max(100, min(int(limit), 1500))})
    request = urllib.request.Request(f"{BASE_URL}?{query}", headers={"User-Agent": "major-5m-research/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        return []
    rows = [_parse_kline(row) for row in payload if isinstance(row, list)]
    return [row for row in rows if row is not None and row["close"] > 0.0]


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [float(values[0])]
    for value in values[1:]:
        out.append((float(value) * alpha) + (out[-1] * (1.0 - alpha)))
    return out


def _mean_quote_volume(bars: list[dict[str, Any]], start: int, end: int) -> float:
    values = [_safe_float(row.get("quote_volume")) for row in bars[max(start, 0) : max(end, 0)]]
    return sum(values) / len(values) if values else 0.0


def build_signals(
    bars: list[dict[str, Any]],
    *,
    symbol: str,
    min_gap_bars: int = 3,
) -> list[dict[str, Any]]:
    rows = sorted(bars, key=lambda row: int(row.get("open_time") or 0))
    closes = [_safe_float(row.get("close")) for row in rows]
    if len(rows) < 120:
        return []
    ema12 = _ema(closes, 12)
    ema36 = _ema(closes, 36)
    signals: list[dict[str, Any]] = []
    last_signal_idx = -999
    max_hold = max(HOLD_BARS)
    for idx in range(40, len(rows) - max_hold - 1):
        if idx - last_signal_idx < min_gap_bars:
            continue
        close = closes[idx]
        ret3 = _ret_bps(closes[idx - 3], close)
        ret6 = _ret_bps(closes[idx - 6], close)
        ret12 = _ret_bps(closes[idx - 12], close)
        vol_recent = _mean_quote_volume(rows, idx - 2, idx + 1)
        vol_base = _mean_quote_volume(rows, idx - 14, idx - 2)
        volume_ratio = vol_recent / vol_base if vol_base > 0.0 else 0.0
        side = ""
        if (
            close > ema12[idx] > ema36[idx]
            and ret3 >= 4.0
            and ret6 >= 6.0
            and ret12 >= 8.0
            and volume_ratio >= 1.05
        ):
            side = "long"
        elif (
            close < ema12[idx] < ema36[idx]
            and ret3 <= -4.0
            and ret6 <= -6.0
            and ret12 <= -8.0
            and volume_ratio >= 1.05
        ):
            side = "short"
        if not side:
            continue
        last_signal_idx = idx
        signals.append(
            {
                "symbol": symbol,
                "bar_index": idx,
                "side": side,
                "timestamp": datetime.fromtimestamp(int(rows[idx]["close_time"]) / 1000.0, UTC).isoformat(),
                "entry_open_time": rows[idx + 1]["open_time"],
                "ret3_bps": round(ret3, 6),
                "ret6_bps": round(ret6, 6),
                "ret12_bps": round(ret12, 6),
                "volume_ratio": round(volume_ratio, 6),
                "ema_fast": round(ema12[idx], 8),
                "ema_slow": round(ema36[idx], 8),
            }
        )
    return signals


def _simulate_trade(
    bars: list[dict[str, Any]],
    signal: dict[str, Any],
    *,
    hold_bars: int,
    leverage: int,
    cost_bps: float = ROUND_TRIP_COST_BPS,
) -> dict[str, Any] | None:
    idx = int(signal["bar_index"])
    entry_idx = idx + 1
    exit_idx = entry_idx + hold_bars
    if entry_idx >= len(bars) or exit_idx >= len(bars):
        return None
    side = str(signal["side"])
    entry = _safe_float(bars[entry_idx].get("open"))
    exit_price = _safe_float(bars[exit_idx].get("close"))
    if entry <= 0.0 or exit_price <= 0.0:
        return None
    window = bars[entry_idx : exit_idx + 1]
    if side == "long":
        gross_bps = _ret_bps(entry, exit_price)
        mae_bps = _ret_bps(entry, min(_safe_float(row.get("low")) for row in window))
        mfe_bps = _ret_bps(entry, max(_safe_float(row.get("high")) for row in window))
    else:
        gross_bps = _ret_bps(exit_price, entry)
        mae_bps = -_ret_bps(entry, max(_safe_float(row.get("high")) for row in window))
        mfe_bps = -_ret_bps(entry, min(_safe_float(row.get("low")) for row in window))
    net_bps = gross_bps - cost_bps
    return {
        "symbol": signal["symbol"],
        "side": side,
        "timestamp": signal["timestamp"],
        "hold_bars": hold_bars,
        "hold_minutes": hold_bars * 5,
        "leverage": leverage,
        "entry_price": round(entry, 8),
        "exit_price": round(exit_price, 8),
        "gross_bps": round(gross_bps, 6),
        "net_bps": round(net_bps, 6),
        "levered_roe_bps": round(net_bps * leverage, 6),
        "mae_bps": round(mae_bps, 6),
        "mfe_bps": round(mfe_bps, 6),
        "mae_roe_bps": round(mae_bps * leverage, 6),
        "mfe_roe_bps": round(mfe_bps * leverage, 6),
    }


def _summarize_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    net = [_safe_float(row.get("net_bps")) for row in trades]
    roe = [_safe_float(row.get("levered_roe_bps")) for row in trades]
    mae_roe = [_safe_float(row.get("mae_roe_bps")) for row in trades]
    if not trades:
        return {
            "count": 0,
            "win_rate": None,
            "avg_net_bps": None,
            "avg_roe_bps": None,
            "worst_roe_bps": None,
            "decision": "sample_too_small",
        }
    count = len(trades)
    win_rate = sum(1 for value in net if value > 0.0) / count
    five_pct_pain = sum(1 for value in mae_roe if value <= -500.0)
    ten_pct_pain = sum(1 for value in mae_roe if value <= -1000.0)
    decision = "reject_or_hold"
    blockers: list[str] = []
    avg_net = _avg(net)
    worst_roe = min(roe)
    leverage = int(trades[0].get("leverage") or 1)
    hold_bars = int(trades[0].get("hold_bars") or 0)
    if count < 8:
        decision = "sample_too_small"
        blockers.append("sample_lt_8")
    if avg_net is not None and avg_net <= 0.0:
        blockers.append("avg_net_lte_0")
    if win_rate < 0.55:
        blockers.append("win_rate_lt_55pct")
    if worst_roe <= -1000.0:
        blockers.append("worst_roe_lte_-10pct")
    if count and five_pct_pain / count >= 0.35:
        blockers.append("five_pct_pain_rate_gte_35pct")
    if count >= 8 and avg_net is not None and avg_net > 0.0 and win_rate >= 0.55 and worst_roe > -1000.0:
        decision = "paper_watch"
    if leverage == 5 and hold_bars >= 36 and decision == "paper_watch" and (ten_pct_pain > 0 or five_pct_pain / count >= 0.2):
        decision = "reject_5x_hold"
        blockers.append("stopless_5x_hold_tail_risk")
    return {
        "count": count,
        "win_rate": round(win_rate, 6),
        "avg_net_bps": avg_net,
        "median_net_bps": _median(net),
        "best_net_bps": round(max(net), 6),
        "worst_net_bps": round(min(net), 6),
        "avg_roe_bps": _avg(roe),
        "median_roe_bps": _median(roe),
        "best_roe_bps": round(max(roe), 6),
        "worst_roe_bps": round(worst_roe, 6),
        "avg_mae_roe_bps": _avg(mae_roe),
        "worst_mae_roe_bps": round(min(mae_roe), 6),
        "five_pct_pain_count": five_pct_pain,
        "ten_pct_pain_count": ten_pct_pain,
        "decision": decision,
        "blockers": blockers,
    }


def build_report(
    bars_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    cost_bps: float = ROUND_TRIP_COST_BPS,
) -> dict[str, Any]:
    all_trades: list[dict[str, Any]] = []
    signals_by_symbol: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for symbol, bars in sorted(bars_by_symbol.items()):
        rows = sorted(bars, key=lambda row: int(row.get("open_time") or 0))
        if len(rows) < 120:
            errors[symbol] = "insufficient_5m_bars"
            signals_by_symbol[symbol] = []
            continue
        signals = build_signals(rows, symbol=symbol)
        signals_by_symbol[symbol] = signals[-25:]
        for signal in signals:
            for hold_bars in HOLD_BARS:
                for leverage in LEVERAGES:
                    trade = _simulate_trade(rows, signal, hold_bars=hold_bars, leverage=leverage, cost_bps=cost_bps)
                    if trade is not None:
                        all_trades.append(trade)

    groups: dict[str, list[dict[str, Any]]] = {}
    for trade in all_trades:
        key = f"{trade['symbol']}|{trade['side']}|hold{trade['hold_minutes']}m|lev{trade['leverage']}x"
        groups.setdefault(key, []).append(trade)
    summaries = {
        key: _summarize_trades(rows)
        for key, rows in sorted(groups.items())
    }
    ranked = sorted(
        summaries.items(),
        key=lambda item: (
            1 if item[1]["decision"] == "paper_watch" else 0,
            _safe_float(item[1].get("avg_roe_bps"), -999999.0),
            _safe_float(item[1].get("win_rate"), 0.0),
            _safe_float(item[1].get("count"), 0.0),
        ),
        reverse=True,
    )
    five_x_hold = {
        key: value
        for key, value in summaries.items()
        if "|lev5x" in key and ("hold180m" in key or "hold360m" in key)
    }
    decisions = {str(row.get("decision")) for row in summaries.values()}
    if "paper_watch" in decisions:
        overall_action = "test_major_5m_overlay_paper_only"
    elif summaries:
        overall_action = "observe_or_reject_current_5m_profiles"
    else:
        overall_action = "insufficient_data"
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "major_5m_leverage_research",
        "paper_only": True,
        "no_order_side_effects": True,
        "source": "binance_usdm_5m_klines",
        "symbols": sorted(bars_by_symbol),
        "cost_bps": cost_bps,
        "hold_bars": list(HOLD_BARS),
        "leverages": list(LEVERAGES),
        "overall_action": overall_action,
        "errors": errors,
        "signal_counts": {symbol: len(signals) for symbol, signals in signals_by_symbol.items()},
        "recent_signals": signals_by_symbol,
        "profile_summaries": summaries,
        "top_profiles": [
            {"id": key, **value}
            for key, value in ranked[:12]
        ],
        "five_x_hold_assessment": five_x_hold,
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Major 5m Leverage Research",
        "",
        f"Generated: {payload['generated_at']}",
        f"Overall action: `{payload['overall_action']}`",
        "",
        "Paper-only. This report does not place, test, cancel, or modify exchange orders.",
        "",
        "## Top Profiles",
        "",
    ]
    for row in list(payload.get("top_profiles") or [])[:10]:
        lines.append(
            f"- `{row['decision']}` `{row['id']}`: n={row['count']} win={row['win_rate']} "
            f"avg_roe={row['avg_roe_bps']} worst_roe={row['worst_roe_bps']} blockers={','.join(row.get('blockers') or []) or 'none'}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--cost-bps", type=float, default=ROUND_TRIP_COST_BPS)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output")
    args = parser.parse_args()

    bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    for symbol in args.symbols or list(DEFAULT_SYMBOLS):
        symbol = str(symbol).upper()
        try:
            bars_by_symbol[symbol] = fetch_klines(symbol, limit=args.limit, timeout=max(args.timeout, 1.0))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"
    report = build_report(bars_by_symbol, cost_bps=max(float(args.cost_bps), 0.0))
    report["fetch_errors"] = errors
    output = Path(args.output)
    _write_json(output, report)
    markdown_output = Path(args.markdown_output) if args.markdown_output else output.with_suffix(".md")
    markdown_output.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if bars_by_symbol else 2


if __name__ == "__main__":
    raise SystemExit(main())
