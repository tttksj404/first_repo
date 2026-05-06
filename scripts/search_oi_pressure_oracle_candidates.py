#!/usr/bin/env python3
"""Search OI-pressure candidates for a third Oracle paper slot.

This is intentionally separate from breakout/CH1-style entries.  It tests
whether open-interest pressure, deleveraging, or leader/lag crowding creates a
different alpha source on Bitget futures.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(r"C:\Users\SSAFY\Desktop\first_repo")
PRICE_ROOTS = [
    ROOT / "quant_runtime" / "historical_top50",
    ROOT / "quant_runtime" / "historical",
]
OI_ROOT = ROOT / "quant_runtime" / "historical"
OUT = ROOT / "quant_binance" / "strategies" / "_scripts" / "g4701_oi_pressure_results.json"

COST_BPS = 24.0
EQUITY = 100.0

PERIODS = {
    "OOS25_OI": (1742911200000, 1767225600000),
    "IS26_OI": (1767225600000, 1775307600000 + 3600000),
}

OI_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
ALT_SYMBOLS = ["ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT", "WIFUSDT", "PEPEUSDT"]


@dataclass
class Trade:
    ts: int
    symbol: str
    side: str
    engine: str
    pnl_usd: float
    ret_bps: float
    liquidated: bool
    exit_reason: str


def _load_price(symbol: str) -> dict[str, np.ndarray] | None:
    path = None
    for root in PRICE_ROOTS:
        candidate = root / symbol / "1h.json"
        if candidate.exists() and candidate.stat().st_size > 0:
            path = candidate
            break
    if path is None:
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if len(raw) < 1000:
        return None
    return {
        "symbol": np.array([symbol] * len(raw), dtype=object),
        "ts": np.array([int(r["open_time"]) for r in raw], dtype=np.int64),
        "open": np.array([float(r["open_price"]) for r in raw], dtype=np.float64),
        "high": np.array([float(r["high_price"]) for r in raw], dtype=np.float64),
        "low": np.array([float(r["low_price"]) for r in raw], dtype=np.float64),
        "close": np.array([float(r["close_price"]) for r in raw], dtype=np.float64),
        "vol": np.array([float(r.get("base_volume", 0.0)) for r in raw], dtype=np.float64),
    }


def _load_oi(symbol: str) -> dict[int, float] | None:
    path = OI_ROOT / symbol / "oi_1h.json"
    if not path.exists() or path.stat().st_size <= 0:
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if len(raw) < 1000:
        return None
    return {int(r["timestamp"]): float(r["open_interest"]) for r in raw}


def ema(x: np.ndarray, period: int) -> np.ndarray:
    out = np.empty_like(x, dtype=np.float64)
    out[0] = x[0]
    a = 2.0 / (period + 1.0)
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1.0 - a) * out[i - 1]
    return out


def rolling_mean(x: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < period:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[period - 1 :] = (c[period:] - c[:-period]) / period
    return out


def enrich_price(arr: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    close = arr["close"]
    high = arr["high"]
    low = arr["low"]
    vol = arr["vol"]
    out = dict(arr)
    for h in [1, 3, 6, 12, 24, 72]:
        r = np.zeros_like(close)
        r[h:] = close[h:] / close[:-h] - 1.0
        out[f"ret_{h}h"] = r
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out["atr_pct"] = ema(tr, 14) / close
    vol_ma = rolling_mean(vol, 24)
    out["vol_ratio"] = np.where(vol_ma > 0, vol / vol_ma, 1.0)
    return out


def attach_oi(price: dict[str, np.ndarray], oi_by_ts: dict[int, float]) -> dict[str, np.ndarray]:
    oi = np.array([oi_by_ts.get(int(ts), np.nan) for ts in price["ts"]], dtype=np.float64)
    out = dict(price)
    out["oi"] = oi
    for h in [1, 3, 6, 12, 24]:
        r = np.full_like(oi, np.nan)
        valid = (oi[h:] > 0) & (oi[:-h] > 0)
        r[h:][valid] = oi[h:][valid] / oi[:-h][valid] - 1.0
        out[f"oi_{h}h"] = r
    return out


def exit_trade(
    d: dict[str, np.ndarray],
    idx: int,
    side: int,
    hold: int,
    tp: float,
    sl: float,
    lev: float,
    size: float,
    engine: str,
) -> Trade | None:
    entry_idx = idx + 1
    if entry_idx + 1 >= len(d["close"]):
        return None
    end = min(entry_idx + hold, len(d["close"]) - 1)
    entry = d["close"][entry_idx]
    if entry <= 0:
        return None
    tp_px = entry * (1 + tp) if side > 0 else entry * (1 - tp)
    sl_px = entry * (1 - sl) if side > 0 else entry * (1 + sl)
    exit_px = d["close"][end]
    reason = "time"
    liquidated = False
    for j in range(entry_idx + 1, end + 1):
        hi = d["high"][j]
        lo = d["low"][j]
        hit_tp = hi >= tp_px if side > 0 else lo <= tp_px
        hit_sl = lo <= sl_px if side > 0 else hi >= sl_px
        adverse = (lo / entry - 1.0) if side > 0 else (entry / hi - 1.0)
        if adverse * lev <= -0.92:
            liquidated = True
            exit_px = entry * (1 - 0.92 / lev) if side > 0 else entry * (1 + 0.92 / lev)
            reason = "liquidation"
            break
        if hit_sl and hit_tp:
            exit_px = sl_px
            reason = "sl"
            break
        if hit_sl:
            exit_px = sl_px
            reason = "sl"
            break
        if hit_tp:
            exit_px = tp_px
            reason = "tp"
            break
    raw = (exit_px / entry - 1.0) * side
    net = raw - COST_BPS / 10000.0
    return Trade(
        ts=int(d["ts"][entry_idx]),
        symbol=str(d["symbol"][entry_idx]),
        side="long" if side > 0 else "short",
        engine=engine,
        pnl_usd=float(EQUITY * size * lev * net),
        ret_bps=float(net * 10000.0),
        liquidated=liquidated,
        exit_reason=reason,
    )


def summarize(trades: list[Trade], days: float) -> dict[str, Any]:
    if not trades:
        return {
            "n": 0,
            "wr": 0.0,
            "pnl_usd": 0.0,
            "annual_pnl_usd": 0.0,
            "monthly_pnl_usd": 0.0,
            "max_dd_usd": 0.0,
            "liquidations": 0,
            "liq_rate": 0.0,
        }
    pnl = np.array([t.pnl_usd for t in trades], dtype=np.float64)
    eq = EQUITY + np.cumsum(pnl)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    total = float(pnl.sum())
    n = len(trades)
    return {
        "n": n,
        "wr": float((pnl > 0).mean()),
        "pnl_usd": round(total, 2),
        "annual_pnl_usd": round(total * 365.0 / max(days, 1.0), 2),
        "monthly_pnl_usd": round(total * 30.0 / max(days, 1.0), 2),
        "max_dd_usd": round(float(dd.max(initial=0.0)), 2),
        "liquidations": int(sum(1 for t in trades if t.liquidated)),
        "liq_rate": round(sum(1 for t in trades if t.liquidated) / n, 4),
        "long_n": int(sum(1 for t in trades if t.side == "long")),
        "short_n": int(sum(1 for t in trades if t.side == "short")),
        "exit_reasons": {k: int(sum(1 for t in trades if t.exit_reason == k)) for k in sorted({t.exit_reason for t in trades})},
    }


def score(spec: dict[str, Any], trades: list[Trade]) -> dict[str, Any]:
    periods = {}
    for name, (start, end) in PERIODS.items():
        days = (end - start) / 86400000.0
        periods[name] = summarize([t for t in trades if start <= t.ts < end], days)
    start = min(v[0] for v in PERIODS.values())
    end = max(v[1] for v in PERIODS.values())
    weighted = summarize([t for t in trades if start <= t.ts < end], (end - start) / 86400000.0)
    min_period_annual = min((p["annual_pnl_usd"] for p in periods.values()), default=0.0)
    result = {
        "id": spec["id"],
        "engine": spec["engine"],
        "spec": spec,
        "periods": periods,
        "weighted": weighted,
        "all_periods_positive": all(p["pnl_usd"] > 0 for p in periods.values()),
        "min_period_annual": min_period_annual,
        "keys": [
            -int(weighted["liquidations"] == 0),
            -int(all(p["pnl_usd"] > 0 for p in periods.values())),
            -weighted["annual_pnl_usd"],
            -weighted["pnl_usd"],
            weighted["max_dd_usd"],
            -weighted["n"],
        ],
    }
    result["checks"] = {
        "n_ge_40": weighted["n"] >= 40,
        "annual_ge_150": weighted["annual_pnl_usd"] >= 150.0,
        "min_period_positive": min_period_annual > 0.0,
        "liq_zero": weighted["liquidations"] == 0,
        "maxdd_le_120": weighted["max_dd_usd"] <= 120.0,
    }
    return result


def cooldown_indices(mask: np.ndarray, cooldown: int) -> list[int]:
    idxs = np.flatnonzero(mask)
    out: list[int] = []
    last = -10**9
    for idx in idxs:
        if int(idx) - last >= cooldown:
            out.append(int(idx))
            last = int(idx)
    return out


def evaluate_own(spec: dict[str, Any], data: dict[str, dict[str, np.ndarray]]) -> dict[str, Any]:
    trades: list[Trade] = []
    for sym in spec["symbols"]:
        d = data[sym]
        valid = np.zeros(len(d["close"]), dtype=bool)
        valid[80 : max(80, len(d["close"]) - spec["hold"] - 2)] = True
        valid &= (d["ts"] >= PERIODS["OOS25_OI"][0]) & np.isfinite(d[f"oi_{spec['window']}h"])
        if spec["engine"] == "oi_pressure_continuation":
            common = valid & (np.abs(d[f"ret_{spec['window']}h"]) >= spec["price_move"]) & (d[f"oi_{spec['window']}h"] >= spec["oi_move"]) & (d["vol_ratio"] >= spec["vol_ratio"])
            long_mask = common & (d[f"ret_{spec['window']}h"] > 0)
            short_mask = common & (d[f"ret_{spec['window']}h"] < 0)
        elif spec["engine"] == "oi_deleveraging_reversal":
            common = valid & (np.abs(d[f"ret_{spec['window']}h"]) >= spec["price_move"]) & (d[f"oi_{spec['window']}h"] <= -spec["oi_drop"]) & (d["vol_ratio"] >= spec["vol_ratio"])
            long_mask = common & (d[f"ret_{spec['window']}h"] < 0)
            short_mask = common & (d[f"ret_{spec['window']}h"] > 0)
        else:
            common = valid & (np.abs(d[f"ret_{spec['window']}h"]) >= spec["price_move"]) & (d[f"oi_{spec['window']}h"] >= spec["oi_move"]) & (d["vol_ratio"] >= spec["vol_ratio"])
            long_mask = common & (d[f"ret_{spec['window']}h"] < 0)
            short_mask = common & (d[f"ret_{spec['window']}h"] > 0)
        for idx in cooldown_indices(long_mask, spec["cooldown"]):
            t = exit_trade(d, idx, 1, spec["hold"], spec["tp"], spec["sl"], spec["lev"], spec["size"], spec["engine"])
            if t:
                trades.append(t)
        for idx in cooldown_indices(short_mask, spec["cooldown"]):
            t = exit_trade(d, idx, -1, spec["hold"], spec["tp"], spec["sl"], spec["lev"], spec["size"], spec["engine"])
            if t:
                trades.append(t)
    trades.sort(key=lambda t: (t.ts, t.symbol, t.side))
    return score(spec, trades)


def evaluate_leader_lag(spec: dict[str, Any], price_data: dict[str, dict[str, np.ndarray]], oi_data: dict[str, dict[str, np.ndarray]]) -> dict[str, Any]:
    leader = spec["leader"]
    ld = oi_data[leader]
    lead_by_ts = {int(ts): i for i, ts in enumerate(ld["ts"])}
    trades: list[Trade] = []
    for sym in spec["targets"]:
        if sym == leader:
            continue
        d = price_data[sym]
        mask_long = np.zeros(len(d["close"]), dtype=bool)
        mask_short = np.zeros(len(d["close"]), dtype=bool)
        for i, ts in enumerate(d["ts"]):
            li = lead_by_ts.get(int(ts))
            if li is None or li < 80 or i < 80 or i + spec["hold"] + 2 >= len(d["close"]):
                continue
            lead_ret = ld[f"ret_{spec['window']}h"][li]
            lead_oi = ld[f"oi_{spec['window']}h"][li]
            if not np.isfinite(lead_oi):
                continue
            target_lag = d["ret_3h"][i]
            if spec["mode"] == "pressure_follow":
                if lead_ret >= spec["leader_move"] and lead_oi >= spec["leader_oi"] and target_lag <= spec["lag_cap"]:
                    mask_long[i] = True
                elif lead_ret <= -spec["leader_move"] and lead_oi >= spec["leader_oi"] and target_lag >= -spec["lag_cap"]:
                    mask_short[i] = True
            elif spec["mode"] == "delev_fade":
                if lead_ret <= -spec["leader_move"] and lead_oi <= -spec["leader_oi"] and target_lag <= spec["lag_cap"]:
                    mask_long[i] = True
                elif lead_ret >= spec["leader_move"] and lead_oi <= -spec["leader_oi"] and target_lag >= -spec["lag_cap"]:
                    mask_short[i] = True
            else:
                if lead_ret >= spec["leader_move"] and lead_oi >= spec["leader_oi"] and target_lag >= spec["target_move"]:
                    mask_short[i] = True
                elif lead_ret <= -spec["leader_move"] and lead_oi >= spec["leader_oi"] and target_lag <= -spec["target_move"]:
                    mask_long[i] = True
        for idx in cooldown_indices(mask_long, spec["cooldown"]):
            t = exit_trade(d, idx, 1, spec["hold"], spec["tp"], spec["sl"], spec["lev"], spec["size"], spec["engine"])
            if t:
                trades.append(t)
        for idx in cooldown_indices(mask_short, spec["cooldown"]):
            t = exit_trade(d, idx, -1, spec["hold"], spec["tp"], spec["sl"], spec["lev"], spec["size"], spec["engine"])
            if t:
                trades.append(t)
    trades.sort(key=lambda t: (t.ts, t.symbol, t.side))
    return score(spec, trades)


def main() -> int:
    price_data: dict[str, dict[str, np.ndarray]] = {}
    for sym in sorted(set(ALT_SYMBOLS + OI_SYMBOLS)):
        p = _load_price(sym)
        if p is not None:
            price_data[sym] = enrich_price(p)
    oi_data: dict[str, dict[str, np.ndarray]] = {}
    for sym in OI_SYMBOLS:
        oi = _load_oi(sym)
        if oi and sym in price_data:
            oi_data[sym] = attach_oi(price_data[sym], oi)
    print(f"loaded price={len(price_data)} oi={list(oi_data)}")

    results: list[dict[str, Any]] = []
    gid = 8000
    own_symbols = list(oi_data)
    for engine, window, price_move, oi_move, volr, hold, tp, sl, lev, size in product(
        ["oi_pressure_continuation", "oi_deleveraging_reversal", "oi_crowded_fade"],
        [6, 12],
        [0.04, 0.065, 0.10],
        [0.02, 0.04, 0.07],
        [1.0],
        [6, 12],
        [0.05, 0.08],
        [0.025, 0.04],
        [3, 5, 8],
        [0.35],
    ):
        if tp < sl * 0.6:
            continue
        spec = {
            "id": f"G{gid}",
            "engine": engine,
            "symbols": own_symbols,
            "window": window,
            "price_move": price_move,
            "oi_move": oi_move,
            "oi_drop": oi_move,
            "vol_ratio": volr,
            "hold": hold,
            "tp": tp,
            "sl": sl,
            "lev": lev,
            "size": size,
            "cooldown": hold,
        }
        results.append(evaluate_own(spec, oi_data))
        gid += 1
        if gid % 1000 == 0:
            print(f"own specs to G{gid}", flush=True)

    if "--own-only" in sys.argv:
        for r in results:
            r.pop("keys", None)
        ranked = sorted(results, key=lambda r: [
            -int(r["weighted"]["liquidations"] == 0),
            -int(r["all_periods_positive"]),
            -r["weighted"]["annual_pnl_usd"],
            -r["weighted"]["pnl_usd"],
            r["weighted"]["max_dd_usd"],
            -r["weighted"]["n"],
        ])
        strict = [
            r for r in ranked
            if r["checks"]["n_ge_40"]
            and r["checks"]["annual_ge_150"]
            and r["checks"]["min_period_positive"]
            and r["checks"]["liq_zero"]
            and r["checks"]["maxdd_le_120"]
        ]
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"n_specs": len(results), "n_strict": len(strict), "strict": strict[:50], "top": ranked[:200]}, indent=2), encoding="utf-8")
        print(f"wrote {OUT}")
        print(f"n_specs={len(results)} n_strict={len(strict)}")
        for r in ranked[:10]:
            print(r["id"], r["engine"], r["weighted"], r["all_periods_positive"], r["spec"])
        return 0

    targets = [s for s in ALT_SYMBOLS if s in price_data]
    for leader, mode, window, lm, loi, lag, tm, hold, tp, sl, lev, size in product(
        ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        ["pressure_follow", "delev_fade", "crowded_cross_fade"],
        [3, 6, 12],
        [0.02, 0.035, 0.055],
        [0.01, 0.02, 0.035],
        [0.0, 0.025],
        [0.025, 0.05],
        [6, 12, 24],
        [0.03, 0.05, 0.08],
        [0.025, 0.04],
        [3, 5, 8],
        [0.2, 0.35],
    ):
        if leader not in oi_data or tp < sl * 0.6:
            continue
        spec = {
            "id": f"G{gid}",
            "engine": "oi_leader_lag",
            "leader": leader,
            "targets": targets,
            "mode": mode,
            "window": window,
            "leader_move": lm,
            "leader_oi": loi,
            "lag_cap": lag,
            "target_move": tm,
            "hold": hold,
            "tp": tp,
            "sl": sl,
            "lev": lev,
            "size": size,
            "cooldown": hold,
        }
        results.append(evaluate_leader_lag(spec, price_data, oi_data))
        gid += 1
        if gid % 1000 == 0:
            print(f"leader specs to G{gid}", flush=True)

    for r in results:
        r.pop("keys", None)
    ranked = sorted(results, key=lambda r: [
        -int(r["weighted"]["liquidations"] == 0),
        -int(r["all_periods_positive"]),
        -r["weighted"]["annual_pnl_usd"],
        -r["weighted"]["pnl_usd"],
        r["weighted"]["max_dd_usd"],
        -r["weighted"]["n"],
    ])
    strict = [
        r for r in ranked
        if r["checks"]["n_ge_40"]
        and r["checks"]["annual_ge_150"]
        and r["checks"]["min_period_positive"]
        and r["checks"]["liq_zero"]
        and r["checks"]["maxdd_le_120"]
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"n_specs": len(results), "n_strict": len(strict), "strict": strict[:50], "top": ranked[:200]}, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"n_specs={len(results)} n_strict={len(strict)}")
    for r in ranked[:10]:
        print(r["id"], r["engine"], r["weighted"], r["all_periods_positive"], r["spec"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
