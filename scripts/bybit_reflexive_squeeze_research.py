#!/usr/bin/env python3
"""Bybit reflexive squeeze research.

Theory under test:
  The best small-account directional setup is not candle breakout itself.
  It is a reflexive squeeze where price rises *because* new perp risk is being
  added across the target and its leaders. For PEPE, only test:

    A) follow: 1000PEPEUSDT newLongs + BTCUSDT newLongs + ETHUSDT newLongs
    B) fade:   the same crowded newLongs condition, but short it when recent
               data says the crowd is late rather than early.

This script uses Bybit public market endpoints only, fetches recent 5m klines
and 5m open interest, replays one-position-at-a-time paper entries, and ranks
exit profiles after conservative round-trip cost.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "quant_runtime" / "cache" / "bybit_reflexive_squeeze"
OUT = ROOT / "quant_runtime" / "output" / "bybit_reflexive_squeeze_research.json"
BASE_URL = "https://api.bybit.com"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "1000PEPEUSDT")


@dataclass(frozen=True)
class Bar:
    ts: int
    o: float
    h: float
    l: float
    c: float
    oi: float


@dataclass(frozen=True)
class Trade:
    strategy: str
    entry_ts: int
    exit_ts: int
    entry: float
    exit: float
    gross_bps: float
    net_bps: float
    reason: str
    hold_bars: int


def _utc_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _http_json(path: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE_URL}{path}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "bybit-reflexive-squeeze-research/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if int(payload.get("retCode", -1)) != 0:
        raise RuntimeError(f"{path}: {payload.get('retCode')} {payload.get('retMsg')}")
    return payload


def _cache_path(kind: str, symbol: str, start_ms: int, end_ms: int) -> Path:
    return CACHE / f"{kind}_{symbol}_{start_ms}_{end_ms}.json"


def fetch_klines(symbol: str, *, start_ms: int, end_ms: int, use_cache: bool) -> list[dict[str, Any]]:
    path = _cache_path("kline5m", symbol, start_ms, end_ms)
    if use_cache and path.exists():
        return json.loads(path.read_text())
    rows: dict[int, dict[str, Any]] = {}
    end_cursor = end_ms
    while end_cursor > start_ms:
        payload = _http_json(
            "/v5/market/kline",
            {
                "category": "linear",
                "symbol": symbol,
                "interval": "5",
                "start": start_ms,
                "end": end_cursor,
                "limit": 1000,
            },
        )
        batch = payload.get("result", {}).get("list", [])
        if not batch:
            break
        parsed = []
        for item in batch:
            if isinstance(item, list) and len(item) >= 5:
                parsed.append(
                    {
                        "ts": int(item[0]),
                        "o": _safe_float(item[1]),
                        "h": _safe_float(item[2]),
                        "l": _safe_float(item[3]),
                        "c": _safe_float(item[4]),
                    }
                )
        if not parsed:
            break
        for row in parsed:
            rows[row["ts"]] = row
        min_ts = min(row["ts"] for row in parsed)
        if min_ts >= end_cursor:
            break
        end_cursor = min_ts - 300_000
        time.sleep(0.05)
    out = [rows[k] for k in sorted(rows) if start_ms <= k <= end_ms]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


def fetch_open_interest(symbol: str, *, start_ms: int, end_ms: int, use_cache: bool) -> list[dict[str, Any]]:
    path = _cache_path("oi5m", symbol, start_ms, end_ms)
    if use_cache and path.exists():
        return json.loads(path.read_text())
    rows: dict[int, dict[str, Any]] = {}
    cursor: str | None = None
    while True:
        payload = _http_json(
            "/v5/market/open-interest",
            {
                "category": "linear",
                "symbol": symbol,
                "intervalTime": "5min",
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 200,
                "cursor": cursor,
            },
        )
        result = payload.get("result", {})
        batch = result.get("list", [])
        if not batch:
            break
        for item in batch:
            ts = int(item.get("timestamp") or 0)
            if start_ms <= ts <= end_ms:
                rows[ts] = {"ts": ts, "oi": _safe_float(item.get("openInterest"))}
        next_cursor = result.get("nextPageCursor")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        time.sleep(0.05)
    out = [rows[k] for k in sorted(rows)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


def load_symbol(symbol: str, *, start_ms: int, end_ms: int, use_cache: bool) -> list[Bar]:
    klines = fetch_klines(symbol, start_ms=start_ms, end_ms=end_ms, use_cache=use_cache)
    oi_rows = fetch_open_interest(symbol, start_ms=start_ms, end_ms=end_ms, use_cache=use_cache)
    oi_by_ts = {int(row["ts"]): _safe_float(row["oi"]) for row in oi_rows}
    out: list[Bar] = []
    last_oi = 0.0
    for row in sorted(klines, key=lambda r: int(r["ts"])):
        ts = int(row["ts"])
        if ts in oi_by_ts:
            last_oi = oi_by_ts[ts]
        if last_oi <= 0.0:
            continue
        out.append(
            Bar(
                ts=ts,
                o=_safe_float(row["o"]),
                h=_safe_float(row["h"]),
                l=_safe_float(row["l"]),
                c=_safe_float(row["c"]),
                oi=last_oi,
            )
        )
    return out


def pct(new: float, old: float) -> float:
    return 0.0 if old <= 0.0 else new / old - 1.0


def quadrant(price_delta: float, oi_delta: float) -> str:
    if price_delta > 0 and oi_delta > 0:
        return "newLongs"
    if price_delta > 0 and oi_delta <= 0:
        return "shortCover"
    if price_delta <= 0 and oi_delta > 0:
        return "newShorts"
    return "longUnwind"


def state_at(rows: list[Bar], i: int, lookback: int) -> tuple[str, float, float]:
    if i - lookback < 0:
        return "", 0.0, 0.0
    p = pct(rows[i].c, rows[i - lookback].c)
    oi = pct(rows[i].oi, rows[i - lookback].oi)
    return quadrant(p, oi), p, oi


def aligned_data(data: dict[str, list[Bar]]) -> dict[str, list[Bar]]:
    common = set.intersection(*(set(row.ts for row in rows) for rows in data.values()))
    out: dict[str, list[Bar]] = {}
    for sym, rows in data.items():
        by_ts = {row.ts: row for row in rows}
        out[sym] = [by_ts[ts] for ts in sorted(common)]
    return out


def signal_ok(aligned: dict[str, list[Bar]], i: int, *, lookback: int, mode: str, min_price: float, min_oi: float) -> bool:
    pepe_q, pepe_p, pepe_oi = state_at(aligned["1000PEPEUSDT"], i, lookback)
    btc_q, btc_p, btc_oi = state_at(aligned["BTCUSDT"], i, lookback)
    eth_q, eth_p, eth_oi = state_at(aligned["ETHUSDT"], i, lookback)
    if mode in {"pepe_only", "fade_pepe_only"}:
        return pepe_q == "newLongs" and pepe_p >= min_price and pepe_oi >= min_oi
    if mode in {"pepe_btc", "fade_pepe_btc"}:
        return (
            pepe_q == "newLongs"
            and btc_q == "newLongs"
            and pepe_p >= min_price
            and pepe_oi >= min_oi
            and btc_p > 0
            and btc_oi > 0
        )
    if mode in {"triple", "fade_triple"}:
        return (
            pepe_q == "newLongs"
            and btc_q == "newLongs"
            and eth_q == "newLongs"
            and pepe_p >= min_price
            and pepe_oi >= min_oi
            and btc_p > 0
            and eth_p > 0
            and btc_oi > 0
            and eth_oi > 0
        )
    if mode == "trap_short":
        return (
            pepe_q == "newLongs"
            and pepe_p >= min_price
            and pepe_oi >= min_oi
            and (btc_q in {"shortCover", "longUnwind", "newShorts"} or eth_q in {"shortCover", "longUnwind", "newShorts"})
        )
    if mode == "capitulation_bounce":
        return (
            pepe_q == "newShorts"
            and abs(pepe_p) >= min_price
            and pepe_oi >= min_oi
            and btc_q not in {"newShorts", "longUnwind"}
            and eth_q not in {"newShorts", "longUnwind"}
        )
    raise ValueError(mode)


def leader_reversed(aligned: dict[str, list[Bar]], i: int, *, lookback: int) -> bool:
    for sym in ("BTCUSDT", "ETHUSDT"):
        q, p, _ = state_at(aligned[sym], i, lookback)
        if q in {"newShorts", "longUnwind"} and p < 0:
            return True
    return False


def replay(aligned: dict[str, list[Bar]], cfg: dict[str, Any]) -> list[Trade]:
    p = aligned["1000PEPEUSDT"]
    trades: list[Trade] = []
    i = max(cfg["lookback"], 3)
    last_exit = -999999
    while i < len(p) - cfg["max_hold"] - 2:
        if i - last_exit < cfg["cooldown"]:
            i += 1
            continue
        if not signal_ok(aligned, i, lookback=cfg["lookback"], mode=cfg["mode"], min_price=cfg["min_price"], min_oi=cfg["min_oi"]):
            i += 1
            continue
        entry_i = i + 1
        entry = p[entry_i].o
        if entry <= 0.0:
            i += 1
            continue
        side_mult = 1.0 if cfg["side"] == "long" else -1.0
        stop = entry * (1.0 - side_mult * cfg["sl_bps"] / 10000.0)
        target = entry * (1.0 + side_mult * cfg["tp_bps"] / 10000.0)
        exit_i = min(entry_i + cfg["max_hold"], len(p) - 1)
        exit_px = p[exit_i].c
        reason = "TIME"
        for j in range(entry_i + 1, exit_i + 1):
            if cfg.get("leader_exit") and leader_reversed(aligned, j, lookback=cfg["lookback"]):
                exit_i, exit_px, reason = j, p[j].c, "LEADER_REVERSAL"
                break
            if cfg["side"] == "long":
                hit_stop = p[j].l <= stop
                hit_target = p[j].h >= target
            else:
                hit_stop = p[j].h >= stop
                hit_target = p[j].l <= target
            if hit_stop and hit_target:
                exit_i, exit_px, reason = j, stop, "SL_SAME_BAR"
                break
            if hit_stop:
                exit_i, exit_px, reason = j, stop, "SL"
                break
            if hit_target:
                exit_i, exit_px, reason = j, target, "TP"
                break
        gross_bps = ((exit_px / entry - 1.0) * side_mult) * 10000.0
        trades.append(
            Trade(
                strategy=cfg["name"],
                entry_ts=p[entry_i].ts,
                exit_ts=p[exit_i].ts,
                entry=entry,
                exit=exit_px,
                gross_bps=round(gross_bps, 6),
                net_bps=round(gross_bps - cfg["cost_bps"], 6),
                reason=reason,
                hold_bars=exit_i - entry_i,
            )
        )
        last_exit = exit_i
        i = exit_i + 1
    return trades


def stats(trades: list[Trade]) -> dict[str, Any]:
    if not trades:
        return {"n": 0}
    vals = [t.net_bps for t in trades]
    wins = [x for x in vals if x > 0]
    losses = [x for x in vals if x <= 0]
    pf = sum(wins) / abs(sum(losses)) if losses else 99.0
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    folds = []
    fold_n = max(1, len(trades) // 4)
    for k in range(4):
        part = vals[k * fold_n : (k + 1) * fold_n if k < 3 else len(vals)]
        folds.append(round(sum(part), 3))
    return {
        "n": len(vals),
        "avg_net_bps": round(statistics.mean(vals), 6),
        "median_net_bps": round(statistics.median(vals), 6),
        "total_net_bps": round(sum(vals), 6),
        "win_rate": round(len(wins) / len(vals), 6),
        "pf": round(pf, 6),
        "worst_net_bps": round(min(vals), 6),
        "best_net_bps": round(max(vals), 6),
        "positive_folds": sum(1 for x in folds if x > 0),
        "fold_net_bps": folds,
        "reasons": reasons,
        "recent5_net_bps": [round(x, 6) for x in vals[-5:]],
    }


def _mode_side(mode: str) -> str:
    if mode.startswith("fade_") or mode == "trap_short":
        return "short"
    return "long"


def configs(args: argparse.Namespace) -> list[dict[str, Any]]:
    out = []
    for mode in ("pepe_only", "pepe_btc", "triple", "fade_pepe_only", "fade_pepe_btc", "fade_triple", "trap_short", "capitulation_bounce"):
        for lookback in (1, 3, 6):
            for tp, sl in ((45.0, 22.0), (60.0, 25.0), (80.0, 30.0)):
                for leader_exit in (False, True):
                    name = f"{mode}_lb{lookback}_tp{int(tp)}_sl{int(sl)}_{'lexit' if leader_exit else 'hold'}"
                    out.append(
                        {
                            "name": name,
                            "mode": mode,
                            "side": _mode_side(mode),
                            "lookback": lookback,
                            "tp_bps": tp,
                            "sl_bps": sl,
                            "max_hold": args.max_hold_bars,
                            "cooldown": args.cooldown_bars,
                            "cost_bps": args.cost_bps,
                            "min_price": args.min_price_bps / 10000.0,
                            "min_oi": args.min_oi_pct / 100.0,
                            "leader_exit": leader_exit,
                        }
                    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--cost-bps", type=float, default=24.0)
    ap.add_argument("--min-price-bps", type=float, default=1.0)
    ap.add_argument("--min-oi-pct", type=float, default=0.01)
    ap.add_argument("--max-hold-bars", type=int, default=12, help="12 5m bars = 60 minutes")
    ap.add_argument("--cooldown-bars", type=int, default=12)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    end = datetime.now(UTC).replace(second=0, microsecond=0)
    start = end - timedelta(days=args.days)
    start_ms = _utc_ms(start)
    end_ms = _utc_ms(end)

    raw = {sym: load_symbol(sym, start_ms=start_ms, end_ms=end_ms, use_cache=not args.no_cache) for sym in SYMBOLS}
    aligned = aligned_data(raw)
    rows = []
    all_trades: dict[str, list[dict[str, Any]]] = {}
    for cfg in configs(args):
        trades = replay(aligned, cfg)
        st = stats(trades)
        if st.get("n", 0) > 0:
            score = st["avg_net_bps"] * min(st["n"], 30) / 30 + st["positive_folds"] * 2 + min(st["pf"], 5)
        else:
            score = -9999.0
        rows.append({"score": round(score, 6), "config": cfg, "stats": st})
        all_trades[cfg["name"]] = [asdict(t) for t in trades]
    rows.sort(key=lambda r: (r["score"], r["stats"].get("positive_folds", 0), r["stats"].get("avg_net_bps", -999)), reverse=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "exchange": "bybit_public_linear",
        "theory": "reflexive_squeeze_new_perp_risk_across_target_and_leaders",
        "symbols": SYMBOLS,
        "window": {"start": _iso(start_ms), "end": _iso(end_ms), "days": args.days},
        "cost_bps": args.cost_bps,
        "aligned_bar_count": len(next(iter(aligned.values()))) if aligned else 0,
        "top": rows[:20],
        "trades_by_config": {r["config"]["name"]: all_trades[r["config"]["name"]] for r in rows[:10]},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Bybit reflexive squeeze research | {payload['window']['start']} -> {payload['window']['end']} | bars={payload['aligned_bar_count']} cost={args.cost_bps}bps")
    print("TOP CONFIGS")
    for rank, row in enumerate(rows[:10], 1):
        st = row["stats"]
        cfg = row["config"]
        print(
            f"{rank:2d}. {cfg['name']:<36} n={st.get('n',0):>3} "
            f"avg={st.get('avg_net_bps',0):>8.3f}bps wr={st.get('win_rate',0)*100:>5.1f}% "
            f"pf={st.get('pf',0):>5.2f} folds={st.get('positive_folds',0)}/4 "
            f"worst={st.get('worst_net_bps',0):>8.3f}"
        )
    print(f"Saved: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
