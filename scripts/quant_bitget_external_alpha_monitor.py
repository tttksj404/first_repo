#!/usr/bin/env python3
"""Paper-only Bitget external-alpha shadow monitor.

This monitor tests strategy ideas that are intentionally orthogonal to the
existing score/edge entry engine:

- crowded-position unwind
- flow momentum
- funding/basis contrarian
- OI expansion confirmation

It uses public Bitget endpoints only, writes shadow candidates, and computes
5/10/15 minute forward outcomes after candidates mature. It never calls private
endpoints and never places, tests, cancels, or modifies exchange orders.
"""

from __future__ import annotations

import argparse
import json
import math
import ssl
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://api.bitget.com"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "PEPEUSDT")
HORIZONS = (5, 10, 15)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _request_json(path: str, params: dict[str, Any], *, insecure_ssl: bool) -> dict[str, Any]:
    query = urlencode(sorted((key, value) for key, value in params.items() if value is not None))
    url = f"{BASE_URL}{path}?{query}" if query else f"{BASE_URL}{path}"
    context = ssl._create_unverified_context() if insecure_ssl else None
    req = Request(url=url, method="GET")
    with urlopen(req, timeout=15, context=context) as response:
        return json.loads(response.read().decode("utf-8"))


def _latest_row(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data")
    if isinstance(data, list) and data:
        row = data[-1]
        return row if isinstance(row, dict) else None
    if isinstance(data, dict):
        return data
    return None


def _open_interest_value(row: dict[str, Any]) -> float:
    value = _safe_float(row.get("size") or row.get("openInterest"))
    if value > 0.0:
        return value
    rows = row.get("openInterestList")
    if isinstance(rows, list) and rows:
        first = rows[0]
        if isinstance(first, dict):
            return _safe_float(first.get("size") or first.get("openInterest"))
    return 0.0


def _fetch_optional(path: str, params: dict[str, Any], *, insecure_ssl: bool) -> tuple[dict[str, Any] | None, str]:
    try:
        payload = _request_json(path, params, insecure_ssl=insecure_ssl)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if str(payload.get("code") or "") not in {"00000", "0", ""}:
        return None, str(payload.get("msg") or payload.get("code") or "api_error")
    return _latest_row(payload), ""


def _fetch_klines(symbol: str, *, limit: int, insecure_ssl: bool) -> list[dict[str, float]]:
    payload = _request_json(
        "/api/v2/mix/market/candles",
        {"symbol": symbol, "productType": "USDT-FUTURES", "granularity": "1m", "limit": limit},
        insecure_ssl=insecure_ssl,
    )
    rows = payload.get("data", [])
    out: list[dict[str, float]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, list) or len(row) < 7:
            continue
        out.append(
            {
                "open_time": float(row[0]),
                "open": _safe_float(row[1]),
                "high": _safe_float(row[2]),
                "low": _safe_float(row[3]),
                "close": _safe_float(row[4]),
                "base_volume": _safe_float(row[5]),
                "quote_volume": _safe_float(row[6]),
            }
        )
    return sorted(out, key=lambda item: item["open_time"])


def _ret_bps(bars: list[dict[str, float]], minutes: int) -> float:
    if len(bars) < minutes + 1:
        return 0.0
    start = bars[-minutes - 1]["close"]
    end = bars[-1]["close"]
    if start <= 0:
        return 0.0
    return ((end / start) - 1.0) * 10000.0


def _spread_bps(ticker: dict[str, Any]) -> float:
    bid = _safe_float(ticker.get("bidPr") or ticker.get("bidPrice"))
    ask = _safe_float(ticker.get("askPr") or ticker.get("askPrice"))
    mid = (bid + ask) / 2.0
    if bid <= 0.0 or ask <= 0.0 or mid <= 0.0:
        return 0.0
    return ((ask - bid) / mid) * 10000.0


def fetch_symbol_metrics(symbol: str, *, insecure_ssl: bool, sleep_seconds: float = 1.05) -> dict[str, Any]:
    errors: dict[str, str] = {}
    ticker, err = _fetch_optional(
        "/api/v2/mix/market/ticker",
        {"symbol": symbol, "productType": "USDT-FUTURES"},
        insecure_ssl=insecure_ssl,
    )
    if err:
        errors["ticker"] = err
    oi, err = _fetch_optional(
        "/api/v2/mix/market/open-interest",
        {"symbol": symbol, "productType": "USDT-FUTURES"},
        insecure_ssl=insecure_ssl,
    )
    if err:
        errors["open_interest"] = err
    time.sleep(sleep_seconds)
    long_short, err = _fetch_optional(
        "/api/v2/mix/market/long-short",
        {"symbol": symbol, "period": "5m"},
        insecure_ssl=insecure_ssl,
    )
    if err:
        errors["long_short"] = err
    time.sleep(sleep_seconds)
    taker, err = _fetch_optional(
        "/api/v2/mix/market/taker-buy-sell",
        {"symbol": symbol, "period": "5m"},
        insecure_ssl=insecure_ssl,
    )
    if err:
        errors["taker_buy_sell"] = err
    time.sleep(sleep_seconds)
    position, err = _fetch_optional(
        "/api/v2/mix/market/position-long-short",
        {"symbol": symbol, "period": "5m"},
        insecure_ssl=insecure_ssl,
    )
    if err:
        errors["position_long_short"] = err
    bars = []
    try:
        bars = _fetch_klines(symbol, limit=75, insecure_ssl=insecure_ssl)
    except Exception as exc:
        errors["klines"] = f"{type(exc).__name__}: {exc}"

    ticker = ticker or {}
    oi = oi or {}
    long_short = long_short or {}
    taker = taker or {}
    position = position or {}
    buy = _safe_float(taker.get("buyVolume"))
    sell = _safe_float(taker.get("sellVolume"))
    taker_ratio = None if buy + sell <= 0.0 else buy / (buy + sell)
    last = _safe_float(ticker.get("lastPr") or ticker.get("markPrice"))
    index_price = _safe_float(ticker.get("indexPrice"), last)
    mark_price = _safe_float(ticker.get("markPrice"), last)
    basis_bps = ((mark_price / index_price) - 1.0) * 10000.0 if index_price > 0.0 else 0.0
    funding = _safe_float(ticker.get("fundingRate"))
    return {
        "symbol": symbol,
        "timestamp": _utc_now().isoformat(),
        "last_price": last,
        "spread_bps": round(_spread_bps(ticker), 6),
        "funding_bps": round(funding * 10000.0, 6),
        "basis_bps": round(basis_bps, 6),
        "open_interest": _open_interest_value(oi),
        "long_ratio": _safe_float(long_short.get("longRatio"), math.nan),
        "short_ratio": _safe_float(long_short.get("shortRatio"), math.nan),
        "long_short_ratio": _safe_float(long_short.get("longShortRatio"), math.nan),
        "position_long_ratio": _safe_float(position.get("longPositionRatio"), math.nan),
        "position_short_ratio": _safe_float(position.get("shortPositionRatio"), math.nan),
        "position_long_short_ratio": _safe_float(position.get("longShortPositionRatio"), math.nan),
        "taker_buy": buy,
        "taker_sell": sell,
        "taker_buy_ratio": None if taker_ratio is None else round(taker_ratio, 6),
        "ret5_bps": round(_ret_bps(bars, 5), 6),
        "ret15_bps": round(_ret_bps(bars, 15), 6),
        "ret60_bps": round(_ret_bps(bars, 60), 6),
        "quote_volume_15m": round(sum(item["quote_volume"] for item in bars[-15:]), 6) if bars else 0.0,
        "errors": errors,
    }


def _ratio_ok(value: Any) -> bool:
    try:
        return not math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def _make_candidate(symbol: str, strategy: str, side: str, score: float, metrics: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {
        "timestamp": _utc_now().isoformat(),
        "symbol": symbol,
        "strategy": strategy,
        "side": side,
        "score": round(score, 6),
        "reference_price": metrics.get("last_price"),
        "paper_only": True,
        "reasons": reasons,
        "metrics": metrics,
    }


def generate_candidates(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    symbol = str(metrics["symbol"])
    candidates: list[dict[str, Any]] = []
    taker = metrics.get("taker_buy_ratio")
    long_ratio = metrics.get("long_ratio")
    short_ratio = metrics.get("short_ratio")
    pos_long = metrics.get("position_long_ratio")
    pos_short = metrics.get("position_short_ratio")
    ret5 = _safe_float(metrics.get("ret5_bps"))
    ret15 = _safe_float(metrics.get("ret15_bps"))
    ret60 = _safe_float(metrics.get("ret60_bps"))
    spread = _safe_float(metrics.get("spread_bps"))
    funding_bps = _safe_float(metrics.get("funding_bps"))
    oi = _safe_float(metrics.get("open_interest"))

    if taker is not None and (_ratio_ok(long_ratio) or _ratio_ok(pos_long)):
        crowd_long = max(_safe_float(long_ratio), _safe_float(pos_long))
        crowd_short = max(_safe_float(short_ratio), _safe_float(pos_short))
        if crowd_long >= 0.68 and taker <= 0.35:
            score = 60 + (crowd_long - 0.68) * 80 + (0.35 - taker) * 80 + max(-ret5, 0) * 0.05
            candidates.append(
                _make_candidate(
                    symbol,
                    "crowded_long_unwind",
                    "short",
                    score,
                    metrics,
                    ["long_crowding", "taker_sell_dominance", "unwind_short_candidate"],
                )
            )
        if crowd_short >= 0.58 and taker >= 0.65:
            score = 58 + (crowd_short - 0.58) * 80 + (taker - 0.65) * 70 + max(ret5, 0) * 0.05
            candidates.append(
                _make_candidate(
                    symbol,
                    "crowded_short_squeeze",
                    "long",
                    score,
                    metrics,
                    ["short_crowding", "taker_buy_dominance", "squeeze_long_candidate"],
                )
            )

    if taker is not None:
        if taker >= 0.70 and ret5 > 0 and ret15 > -15:
            candidates.append(
                _make_candidate(
                    symbol,
                    "flow_momentum",
                    "long",
                    55 + (taker - 0.70) * 80 + max(ret5, 0) * 0.08,
                    metrics,
                    ["taker_buy_dominance", "positive_short_momentum"],
                )
            )
        if taker <= 0.30 and ret5 < 0 and ret15 < 15:
            candidates.append(
                _make_candidate(
                    symbol,
                    "flow_momentum",
                    "short",
                    55 + (0.30 - taker) * 80 + max(-ret5, 0) * 0.08,
                    metrics,
                    ["taker_sell_dominance", "negative_short_momentum"],
                )
            )

    if funding_bps >= 1.2 and taker is not None and taker <= 0.45:
        candidates.append(
            _make_candidate(
                symbol,
                "funding_contrarian",
                "short",
                52 + funding_bps * 2.0 + (0.45 - taker) * 60,
                metrics,
                ["positive_funding", "flow_not_supporting_longs"],
            )
        )
    if funding_bps <= -1.2 and taker is not None and taker >= 0.55:
        candidates.append(
            _make_candidate(
                symbol,
                "funding_contrarian",
                "long",
                52 + abs(funding_bps) * 2.0 + (taker - 0.55) * 60,
                metrics,
                ["negative_funding", "flow_supporting_longs"],
            )
        )

    if oi > 0.0 and spread <= 1.5 and abs(ret15) >= 8.0:
        side = "long" if ret15 > 0 else "short"
        candidates.append(
            _make_candidate(
                symbol,
                "oi_momentum_breakout",
                side,
                50 + abs(ret15) * 0.12 + max(0.0, 1.5 - spread) * 2.0,
                metrics,
                ["open_interest_present", "fifteen_minute_momentum", "spread_ok"],
            )
        )

    insight_unavailable = bool(metrics.get("errors", {}).get("taker_buy_sell")) or taker is None
    if insight_unavailable and oi > 0.0 and spread <= 1.8 and abs(ret5) >= 4.0 and abs(ret15) >= 8.0:
        side = "long" if ret5 + ret15 > 0 else "short"
        candidates.append(
            _make_candidate(
                symbol,
                "oi_price_fallback_momentum",
                side,
                48 + abs(ret5) * 0.10 + abs(ret15) * 0.08 + max(0.0, 1.8 - spread),
                metrics,
                ["insight_endpoint_unavailable", "open_interest_present", "price_momentum_fallback"],
            )
        )

    if oi > 0.0 and spread <= 2.0 and abs(ret60) >= 45.0 and abs(ret5) <= 8.0:
        side = "short" if ret60 > 0 else "long"
        candidates.append(
            _make_candidate(
                symbol,
                "oi_exhaustion_reversion",
                side,
                46 + abs(ret60) * 0.06 + max(0.0, 2.0 - spread),
                metrics,
                ["open_interest_present", "sixty_minute_extension", "short_term_stall"],
            )
        )

    return sorted(candidates, key=lambda item: float(item["score"]), reverse=True)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")


def _candidate_id(row: dict[str, Any]) -> str:
    return "|".join([str(row.get("timestamp")), str(row.get("symbol")), str(row.get("strategy")), str(row.get("side"))])


def evaluate_mature_candidates(candidates_path: Path, *, insecure_ssl: bool) -> list[dict[str, Any]]:
    rows = _load_jsonl(candidates_path)
    now = _utc_now()
    outcomes: list[dict[str, Any]] = []
    for row in rows:
        try:
            ts = datetime.fromisoformat(str(row.get("timestamp")).replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            continue
        if ts > now - timedelta(minutes=max(HORIZONS)):
            continue
        symbol = str(row.get("symbol") or "")
        ref = _safe_float(row.get("reference_price"))
        if not symbol or ref <= 0:
            continue
        start_ms = int(ts.timestamp() * 1000)
        end_ms = int((ts + timedelta(minutes=max(HORIZONS) + 1)).timestamp() * 1000)
        try:
            payload = _request_json(
                "/api/v2/mix/market/candles",
                {
                    "symbol": symbol,
                    "productType": "USDT-FUTURES",
                    "granularity": "1m",
                    "limit": 25,
                    "startTime": start_ms,
                    "endTime": end_ms,
                },
                insecure_ssl=insecure_ssl,
            )
        except Exception:
            continue
        bars = []
        for item in payload.get("data", []) if isinstance(payload.get("data"), list) else []:
            if isinstance(item, list) and len(item) >= 5:
                bars.append({"open_time": int(item[0]), "close": _safe_float(item[4])})
        bars.sort(key=lambda item: item["open_time"])
        if not bars:
            continue
        side = str(row.get("side") or "long")
        sign = -1.0 if side == "short" else 1.0
        outcome = {
            "candidate_id": _candidate_id(row),
            "timestamp": row.get("timestamp"),
            "symbol": symbol,
            "strategy": row.get("strategy"),
            "side": side,
            "score": row.get("score"),
            "reference_price": ref,
        }
        ok = True
        for minutes in HORIZONS:
            target_ms = int((ts + timedelta(minutes=minutes)).timestamp() * 1000)
            prior = [bar for bar in bars if int(bar["open_time"]) <= target_ms]
            if not prior:
                ok = False
                break
            close = _safe_float(prior[-1]["close"])
            outcome[f"ret{minutes}_bps"] = round(sign * ((close / ref) - 1.0) * 10000.0, 6)
        if ok:
            outcomes.append(outcome)
    # Dedupe by candidate id.
    deduped: dict[str, dict[str, Any]] = {}
    for row in outcomes:
        deduped[str(row["candidate_id"])] = row
    return list(deduped.values())


def summarize(candidates: list[dict[str, Any]], outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in outcomes:
        key = f"{row.get('symbol')}|{row.get('strategy')}|{row.get('side')}"
        groups.setdefault(key, []).append(row)
    outcome_summary: dict[str, Any] = {}
    for key, rows in sorted(groups.items()):
        net15 = [_safe_float(row.get("ret15_bps")) for row in rows]
        outcome_summary[key] = {
            "count": len(rows),
            "avg_ret15_bps": round(sum(net15) / len(net15), 6) if net15 else 0.0,
            "win15_rate": round(sum(1 for value in net15 if value > 0.0) / len(net15), 6) if net15 else 0.0,
            "recent5_ret15_bps": [round(value, 6) for value in net15[-5:]],
            "latest_ret15_bps": round(net15[-1], 6) if net15 else None,
        }
    candidate_counts: dict[str, int] = {}
    for row in candidates:
        key = f"{row.get('symbol')}|{row.get('strategy')}|{row.get('side')}"
        candidate_counts[key] = candidate_counts.get(key, 0) + 1
    ranked = sorted(outcome_summary.items(), key=lambda item: (item[1]["count"] >= 3, item[1]["avg_ret15_bps"]), reverse=True)
    return {
        "generated_at": _utc_now().isoformat(),
        "candidate_count": len(candidates),
        "mature_outcome_count": len(outcomes),
        "candidate_counts": candidate_counts,
        "outcome_summary": outcome_summary,
        "best_mature_candidates": [{"key": key, **value} for key, value in ranked[:8]],
    }


def run_cycle(output_dir: Path, *, insecure_ssl: bool) -> dict[str, Any]:
    metrics_rows = [fetch_symbol_metrics(symbol, insecure_ssl=insecure_ssl) for symbol in SYMBOLS]
    candidates: list[dict[str, Any]] = []
    for metrics in metrics_rows:
        per_symbol = generate_candidates(metrics)
        candidates.extend(per_symbol[:3])
    now_tag = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    cycle_dir = output_dir / f"cycle_{now_tag}"
    _write_json(cycle_dir / "metrics.json", {"generated_at": _utc_now().isoformat(), "rows": metrics_rows})
    _write_json(cycle_dir / "candidate_matrix.json", {"generated_at": _utc_now().isoformat(), "candidates": candidates})
    for row in candidates:
        _append_jsonl(output_dir / "external_alpha_candidates.jsonl", row)
    outcomes = evaluate_mature_candidates(output_dir / "external_alpha_candidates.jsonl", insecure_ssl=insecure_ssl)
    _write_json(output_dir / "external_alpha_outcomes.json", {"generated_at": _utc_now().isoformat(), "outcomes": outcomes})
    summary = summarize(_load_jsonl(output_dir / "external_alpha_candidates.jsonl"), outcomes)
    summary["latest_cycle_dir"] = str(cycle_dir)
    summary["top_current_candidates"] = candidates[:10]
    _write_json(output_dir / "status.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, default=_json_default), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Bitget paper-only external alpha shadow monitor.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--duration-minutes", type=int, default=0)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--insecure-ssl", action="store_true")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    process = {
        "started_at": _utc_now().isoformat(),
        "paper_only": True,
        "public_endpoints_only": True,
        "live_orders_disabled": True,
        "duration_minutes": args.duration_minutes,
        "interval_seconds": args.interval_seconds,
    }
    _write_json(output_dir / "external_alpha_process.json", process)
    end_at = _utc_now() + timedelta(minutes=args.duration_minutes) if args.duration_minutes > 0 else None
    while True:
        run_cycle(output_dir, insecure_ssl=args.insecure_ssl)
        if end_at is None or _utc_now() >= end_at:
            break
        time.sleep(min(args.interval_seconds, max(1, int((end_at - _utc_now()).total_seconds()))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
