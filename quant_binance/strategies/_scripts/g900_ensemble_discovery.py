"""G900 ensemble discovery.

Goal:
  Find strategy combinations that are not just parameter variants of the
  existing CH1 lottery core.

Engines:
  - ch1_core: proven sparse long lottery/reversion sleeve.
  - structure: 1h breakout/breakdown long-short alpha.
  - funding_fade: contrarian funding/crowding alpha.

Combiners:
  - single engine baselines.
  - parallel sleeve: independent engines trade together, with same-symbol
    conflicts resolved by confidence.

This is research backtest evidence only. It is not live-trading approval.
"""
from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\SSAFY\Desktop\first_repo")
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g002_mingogogo_ch1_backtest import atr_pct, compute_ch1_score  # type: ignore

DATA_22 = ROOT / "quant_runtime" / "historical_2022"
DATA_24 = ROOT / "quant_runtime" / "historical_2024"
DATA_25 = ROOT / "quant_runtime" / "historical_is25"
FUNDING = ROOT / "quant_runtime" / "funding_binance"
OUT = SCRIPTS / "g900_ensemble_discovery_results.json"

UNIV_22 = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT", "DOGEUSDT",
    "DOTUSDT", "LINKUSDT", "LTCUSDT", "AVAXUSDT", "MATICUSDT",
    "NEARUSDT", "UNIUSDT", "XRPUSDT",
]
UNIV_24 = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT", "DOGEUSDT",
    "DOTUSDT", "LINKUSDT", "LTCUSDT", "AVAXUSDT", "NEARUSDT",
    "UNIUSDT", "XRPUSDT", "OPUSDT", "ARBUSDT", "APTUSDT", "PEPEUSDT",
    "SUIUSDT",
]
UNIV_25 = [
    "DOGEUSDT", "PEPEUSDT", "WIFUSDT", "ARBUSDT", "OPUSDT", "AVAXUSDT",
    "SUIUSDT", "ADAUSDT", "APTUSDT", "BNBUSDT", "DOTUSDT", "LINKUSDT",
    "LTCUSDT", "NEARUSDT", "SOLUSDT", "UNIUSDT", "XRPUSDT", "BTCUSDT",
]

DEAD = {"WIFUSDT", "LTCUSDT", "BTCUSDT"}
TOP10 = {"DOGEUSDT", "PEPEUSDT", "SOLUSDT", "ARBUSDT", "ADAUSDT", "LINKUSDT", "DOTUSDT", "NEARUSDT", "AVAXUSDT", "UNIUSDT"}
EQUITY = 100.0
COST_BPS = 24.0


@dataclass(frozen=True)
class Period:
    name: str
    path: Path
    universe: list[str]
    days: int


PERIODS = [
    Period("OOS22-23", DATA_22, UNIV_22, 730),
    Period("OOS24-Q1", DATA_24, UNIV_24, 456),
    Period("IS25-26", DATA_25, UNIV_25, 374),
]


def filter_universe(universe: list[str], mode: str) -> list[str]:
    if mode == "no_dead":
        return [s for s in universe if s not in DEAD]
    if mode == "top10":
        return [s for s in universe if s in TOP10]
    if mode == "meme":
        return [s for s in universe if s in {"DOGEUSDT", "PEPEUSDT", "WIFUSDT"}]
    return list(universe)


def load_funding(sym: str) -> pd.DataFrame | None:
    path = FUNDING / sym / "funding.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data:
        return None
    df = pd.DataFrame(data).rename(columns={"ts": "open_time", "rate": "funding_rate"})
    df = df.sort_values("open_time")
    df["open_time"] = df["open_time"].astype("int64")
    df["funding_rate"] = df["funding_rate"].astype(float)
    return df[["open_time", "funding_rate"]]


def load_symbol_df(data_dir: Path, sym: str) -> pd.DataFrame | None:
    path = data_dir / sym / "1h.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(sorted(data, key=lambda x: x["open_time"]))
    if len(df) < 200:
        return None
    for col in ["open_price", "high_price", "low_price", "close_price", "base_volume", "quote_volume"]:
        df[col] = df[col].astype(float)
    df["open_time"] = df["open_time"].astype("int64")
    score, _ = compute_ch1_score(df)
    df["ch1_score"] = score.astype(float)
    df["atr_pct"] = atr_pct(df["high_price"], df["low_price"], df["close_price"], 14).astype(float)
    df["ret_6h"] = df["close_price"].pct_change(6)
    df["ret_24h"] = df["close_price"].pct_change(24)
    df["roll_hi_24"] = df["high_price"].rolling(24).max().shift(1)
    df["roll_lo_24"] = df["low_price"].rolling(24).min().shift(1)
    df["vol_ratio"] = df["quote_volume"] / df["quote_volume"].rolling(48).median().shift(1)

    fdf = load_funding(sym)
    if fdf is not None:
        df = pd.merge_asof(df.sort_values("open_time"), fdf, on="open_time", direction="backward")
    else:
        df["funding_rate"] = np.nan

    return df.reset_index(drop=True)


def build_period_cache(period: Period, univ_mode: str) -> dict[str, pd.DataFrame]:
    dfs: dict[str, pd.DataFrame] = {}
    for sym in filter_universe(period.universe, univ_mode):
        df = load_symbol_df(period.path, sym)
        if df is not None:
            dfs[sym] = df
    return dfs


def add_btc_regime(dfs: dict[str, pd.DataFrame]) -> None:
    btc = dfs.get("BTCUSDT")
    if btc is None:
        for df in dfs.values():
            df["btc_regime"] = 0.0
        return
    b = btc[["open_time", "close_price"]].copy()
    b["btc_regime"] = b["close_price"].pct_change(72)
    b = b[["open_time", "btc_regime"]]
    for sym, df in list(dfs.items()):
        dfs[sym] = pd.merge_asof(df.sort_values("open_time"), b, on="open_time", direction="backward").reset_index(drop=True)


def event_return(
    df: pd.DataFrame,
    idx: int,
    side: str,
    hold: int,
    leverage: float,
    tp_pct: float | None = None,
    sl_pct: float | None = None,
) -> tuple[float, bool, float]:
    exit_idx = idx + hold
    if exit_idx >= len(df):
        return 0.0, False, 0.0
    entry = float(df.at[idx, "close_price"])
    exit_price = float(df.at[exit_idx, "close_price"])
    path = df.iloc[idx + 1 : exit_idx + 1]
    if entry <= 0 or len(path) == 0:
        return 0.0, False, 0.0

    liq_move = 0.90 / leverage
    adverse = 0.0
    raw: float | None = None
    for _, bar in path.iterrows():
        hi = float(bar["high_price"])
        lo = float(bar["low_price"])
        if side == "long":
            adverse = min(adverse, lo / entry - 1.0)
            if sl_pct is not None and lo <= entry * (1.0 - sl_pct):
                raw = -sl_pct
                break
            if adverse <= -liq_move:
                return -0.90, True, adverse
            if tp_pct is not None and hi >= entry * (1.0 + tp_pct):
                raw = tp_pct
                break
        else:
            adverse = max(adverse, hi / entry - 1.0)
            if sl_pct is not None and hi >= entry * (1.0 + sl_pct):
                raw = -sl_pct
                break
            if adverse >= liq_move:
                return -0.90, True, adverse
            if tp_pct is not None and lo <= entry * (1.0 - tp_pct):
                raw = tp_pct
                break

    if raw is None:
        if side == "long":
            raw = exit_price / entry - 1.0
        else:
            raw = entry / exit_price - 1.0

    net_pct = (raw - COST_BPS / 10000.0) * leverage
    return net_pct, False, adverse


def make_event(
    ts: int,
    sym: str,
    idx: int,
    side: str,
    engine: str,
    hold: int,
    leverage: float,
    size: float,
    confidence: float,
    tp_pct: float | None = None,
    sl_pct: float | None = None,
) -> dict[str, Any]:
    ev = {
        "ts": int(ts),
        "sym": sym,
        "idx": int(idx),
        "side": side,
        "engine": engine,
        "hold": int(hold),
        "lev": float(leverage),
        "size": float(size),
        "confidence": float(confidence),
    }
    if tp_pct is not None:
        ev["tp_pct"] = float(tp_pct)
    if sl_pct is not None:
        ev["sl_pct"] = float(sl_pct)
    return ev


def ch1_events(dfs: dict[str, pd.DataFrame], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, df in dfs.items():
        mask = (
            (df["ch1_score"] >= spec["thr"])
            & (df["atr_pct"] >= spec["atr_min"])
            & (df["atr_pct"] <= spec["atr_max"])
        )
        if "max_funding" in spec:
            mask = mask & (df["funding_rate"].isna() | (df["funding_rate"] <= spec["max_funding"]))
        if "min_btc_regime" in spec:
            mask = mask & (df["btc_regime"] >= spec["min_btc_regime"])
        idxs = np.where(mask.to_numpy(dtype=bool))[0]
        for idx in idxs:
            if idx + spec["hold"] >= len(df):
                continue
            score = float(df.at[idx, "ch1_score"])
            conf = 1.0 + max(0.0, score - spec["thr"]) / 20.0
            out.append(make_event(
                df.at[idx, "open_time"], sym, idx, "long", "ch1", spec["hold"], spec["lev"],
                spec["size"], conf, spec.get("tp_pct"), spec.get("sl_pct")
            ))
    return out


def structure_events(dfs: dict[str, pd.DataFrame], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, df in dfs.items():
        if sym == "BTCUSDT" and spec.get("skip_btc", True):
            continue
        close = df["close_price"]
        btc_gate = spec.get("btc_gate")
        if btc_gate is None:
            long_btc = pd.Series(True, index=df.index)
            short_btc = pd.Series(True, index=df.index)
        else:
            long_btc = df["btc_regime"] > btc_gate
            short_btc = df["btc_regime"] < -btc_gate
        long_mask = (
            (close > df["roll_hi_24"] * (1.0 + spec["break_bps"] / 10000.0))
            & (df["ret_24h"] > spec["mom"])
            & (df["vol_ratio"] >= spec["vol"])
            & long_btc
            & (df["atr_pct"] <= spec["atr_max"])
        )
        short_mask = (
            (close < df["roll_lo_24"] * (1.0 - spec["break_bps"] / 10000.0))
            & (df["ret_24h"] < -spec["mom"])
            & (df["vol_ratio"] >= spec["vol"])
            & short_btc
            & (df["atr_pct"] <= spec["atr_max"])
        )
        for side, mask in [("long", long_mask), ("short", short_mask)]:
            idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
            for idx in idxs:
                if idx + spec["hold"] >= len(df):
                    continue
                vr = float(df.at[idx, "vol_ratio"]) if math.isfinite(float(df.at[idx, "vol_ratio"])) else 1.0
                conf = 0.8 + min(1.2, max(0.0, vr - spec["vol"]) / 2.0)
                out.append(make_event(
                    df.at[idx, "open_time"], sym, idx, side, "structure", spec["hold"], spec["lev"],
                    spec["size"], conf, spec.get("tp_pct"), spec.get("sl_pct")
                ))
    return out


def funding_events(dfs: dict[str, pd.DataFrame], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, df in dfs.items():
        rate = df["funding_rate"]
        short_mask = (rate >= spec["pos_rate"]) & (df["ret_24h"] >= spec["min_abs_ret"])
        long_mask = (rate <= spec["neg_rate"]) & (df["ret_24h"] <= -spec["min_abs_ret"])
        for side, mask in [("short", short_mask), ("long", long_mask)]:
            idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
            for idx in idxs:
                if idx + spec["hold"] >= len(df):
                    continue
                r = abs(float(df.at[idx, "funding_rate"]))
                conf = 0.7 + min(1.3, r / 0.001)
                out.append(make_event(
                    df.at[idx, "open_time"], sym, idx, side, "funding_fade", spec["hold"], spec["lev"],
                    spec["size"], conf, spec.get("tp_pct"), spec.get("sl_pct")
                ))
    return out


def resolve_conflicts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[int, str], dict[str, Any]] = {}
    for ev in events:
        key = (ev["ts"], ev["sym"])
        prev = best.get(key)
        if prev is None or ev["confidence"] > prev["confidence"]:
            best[key] = ev
    return sorted(best.values(), key=lambda e: (e["ts"], -e["confidence"]))


def simulate(events: list[dict[str, Any]], dfs: dict[str, pd.DataFrame], max_conc: int, days: int) -> dict[str, Any]:
    events = resolve_conflicts(events)
    open_pos: list[tuple[int, str]] = []
    pnl = 0.0
    wins = 0
    liq = 0
    taken = 0
    by_engine: dict[str, dict[str, Any]] = {}
    by_side = {"long": {"n": 0, "pnl": 0.0}, "short": {"n": 0, "pnl": 0.0}}
    curve: list[float] = [0.0]

    for ev in events:
        ts = ev["ts"]
        sym = ev["sym"]
        open_pos = [p for p in open_pos if p[0] > ts]
        if any(p[1] == sym for p in open_pos):
            continue
        if len(open_pos) >= max_conc:
            continue
        df = dfs.get(sym)
        if df is None:
            continue
        net_pct, liquidated, _ = event_return(
            df,
            ev["idx"],
            ev["side"],
            ev["hold"],
            ev["lev"],
            ev.get("tp_pct"),
            ev.get("sl_pct"),
        )
        trade_pnl = EQUITY * ev["size"] * net_pct
        pnl += trade_pnl
        curve.append(pnl)
        taken += 1
        if trade_pnl > 0:
            wins += 1
        if liquidated:
            liq += 1
        by_side[ev["side"]]["n"] += 1
        by_side[ev["side"]]["pnl"] += trade_pnl
        eng = by_engine.setdefault(ev["engine"], {"n": 0, "pnl": 0.0, "wins": 0})
        eng["n"] += 1
        eng["pnl"] += trade_pnl
        eng["wins"] += int(trade_pnl > 0)
        open_pos.append((ts + ev["hold"] * 3600 * 1000, sym))

    arr = np.array(curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = peak - arr
    max_dd = float(dd.max()) if len(dd) else 0.0
    for item in by_engine.values():
        item["wr"] = item["wins"] / item["n"] if item["n"] else 0.0
        item["pnl"] = round(item["pnl"], 2)
    return {
        "n": taken,
        "wr": wins / taken if taken else 0.0,
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / days * 365, 2) if days else 0.0,
        "monthly_pnl_usd": round(pnl / days * 30.4, 2) if days else 0.0,
        "liquidations": liq,
        "liq_rate": liq / taken if taken else 0.0,
        "max_dd_usd": round(max_dd, 2),
        "by_engine": by_engine,
        "by_side": {k: {"n": v["n"], "pnl": round(v["pnl"], 2)} for k, v in by_side.items()},
    }


def candidate_specs() -> list[dict[str, Any]]:
    ch1_specs = [
        {"thr": 80, "hold": 24, "atr_min": 0, "atr_max": 10, "lev": 20, "size": 0.20},
        {"thr": 80, "hold": 24, "atr_min": 3, "atr_max": 10, "lev": 20, "size": 0.20},
        {"thr": 80, "hold": 36, "atr_min": 0, "atr_max": 10, "lev": 20, "size": 0.20},
        {"thr": 80, "hold": 36, "atr_min": 3, "atr_max": 10, "lev": 20, "size": 0.20},
        {"thr": 80, "hold": 24, "atr_min": 0, "atr_max": 10, "lev": 10, "size": 0.20},
        {"thr": 80, "hold": 24, "atr_min": 3, "atr_max": 10, "lev": 10, "size": 0.20},
        {"thr": 80, "hold": 36, "atr_min": 0, "atr_max": 10, "lev": 10, "size": 0.20},
        {"thr": 80, "hold": 36, "atr_min": 3, "atr_max": 10, "lev": 10, "size": 0.20},
        {"thr": 80, "hold": 24, "atr_min": 3, "atr_max": 8, "lev": 8, "size": 0.25, "max_funding": 0.0008},
        {"thr": 80, "hold": 36, "atr_min": 3, "atr_max": 8, "lev": 8, "size": 0.25, "max_funding": 0.0008},
        {"thr": 82, "hold": 24, "atr_min": 3, "atr_max": 8, "lev": 8, "size": 0.25, "max_funding": 0.0008},
        {"thr": 80, "hold": 24, "atr_min": 0, "atr_max": 10, "lev": 10, "size": 0.25, "tp_pct": 0.10, "sl_pct": 0.055},
        {"thr": 80, "hold": 36, "atr_min": 0, "atr_max": 10, "lev": 10, "size": 0.25, "tp_pct": 0.12, "sl_pct": 0.060},
        {"thr": 80, "hold": 24, "atr_min": 3, "atr_max": 10, "lev": 8, "size": 0.30, "tp_pct": 0.10, "sl_pct": 0.070},
        {"thr": 80, "hold": 36, "atr_min": 3, "atr_max": 10, "lev": 8, "size": 0.30, "tp_pct": 0.12, "sl_pct": 0.075},
        {"thr": 82, "hold": 24, "atr_min": 3, "atr_max": 8, "lev": 8, "size": 0.30, "tp_pct": 0.10, "sl_pct": 0.070, "max_funding": 0.0008},
    ]
    structure_specs = [
        {"hold": 12, "lev": 8, "size": 0.10, "break_bps": 10, "mom": 0.03, "vol": 1.8, "btc_gate": 0.015, "atr_max": 12},
        {"hold": 24, "lev": 8, "size": 0.10, "break_bps": 10, "mom": 0.04, "vol": 2.2, "btc_gate": 0.020, "atr_max": 12},
        {"hold": 12, "lev": 5, "size": 0.15, "break_bps": 20, "mom": 0.03, "vol": 1.8, "btc_gate": 0.010, "atr_max": 10},
        {"hold": 6, "lev": 5, "size": 0.10, "break_bps": 0, "mom": 0.015, "vol": 1.2, "btc_gate": None, "atr_max": 15},
        {"hold": 12, "lev": 5, "size": 0.10, "break_bps": 0, "mom": 0.020, "vol": 1.4, "btc_gate": None, "atr_max": 12},
        {"hold": 24, "lev": 5, "size": 0.10, "break_bps": 0, "mom": 0.025, "vol": 1.6, "btc_gate": 0.0, "atr_max": 12},
    ]
    funding_specs = [
        {"hold": 8, "lev": 5, "size": 0.12, "pos_rate": 0.0007, "neg_rate": -0.0002, "min_abs_ret": 0.03},
        {"hold": 24, "lev": 5, "size": 0.12, "pos_rate": 0.0010, "neg_rate": -0.0003, "min_abs_ret": 0.04},
    ]

    specs: list[dict[str, Any]] = []
    idx = 900
    for ch1 in ch1_specs:
        specs.append({"id": f"G{idx}", "desc": "ch1_core_path_ref", "univ": "no_dead", "max_conc": 5, "engines": {"ch1": ch1}})
        idx += 1
    for st in structure_specs:
        specs.append({"id": f"G{idx}", "desc": "structure_long_short_only", "univ": "no_dead", "max_conc": 5, "engines": {"structure": st}})
        idx += 1
    for fd in funding_specs:
        specs.append({"id": f"G{idx}", "desc": "funding_fade_only", "univ": "no_dead", "max_conc": 5, "engines": {"funding": fd}})
        idx += 1
    # Only combine structure with strict variants. The relaxed structure variants
    # are kept as baselines, but prior runs showed they produce high-volume
    # cost-negative noise when ensembled broadly.
    for ch1 in ch1_specs[-5:]:
        for st in structure_specs[:3]:
            specs.append({"id": f"G{idx}", "desc": "parallel_ch1_structure", "univ": "no_dead", "max_conc": 5, "engines": {"ch1": ch1, "structure": st}})
            idx += 1
    for ch1 in ch1_specs[-8:]:
        for fd in funding_specs:
            specs.append({"id": f"G{idx}", "desc": "parallel_ch1_funding", "univ": "no_dead", "max_conc": 5, "engines": {"ch1": ch1, "funding": fd}})
            idx += 1
    for ch1 in ch1_specs[-5:]:
        for st in structure_specs[:3]:
            for fd in funding_specs:
                specs.append({"id": f"G{idx}", "desc": "parallel_ch1_structure_funding", "univ": "no_dead", "max_conc": 5, "engines": {"ch1": ch1, "structure": st, "funding": fd}})
                idx += 1
    return specs


def events_for_spec(dfs: dict[str, pd.DataFrame], spec: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    engines = spec["engines"]
    if "ch1" in engines:
        events.extend(ch1_events(dfs, engines["ch1"]))
    if "structure" in engines:
        events.extend(structure_events(dfs, engines["structure"]))
    if "funding" in engines:
        events.extend(funding_events(dfs, engines["funding"]))
    return events


def evaluate_spec(spec: dict[str, Any], period_caches: dict[str, dict[str, pd.DataFrame]]) -> dict[str, Any]:
    period_results: dict[str, Any] = {}
    for period in PERIODS:
        dfs = period_caches[period.name]
        events = events_for_spec(dfs, spec)
        period_results[period.name] = simulate(events, dfs, spec["max_conc"], period.days)

    valid = [r for r in period_results.values() if r["n"] > 0]
    total_n = sum(r["n"] for r in valid)
    total_pnl = sum(r["pnl_usd"] for r in valid)
    total_days = sum(p.days for p in PERIODS if period_results[p.name]["n"] > 0)
    weighted_wr = sum(r["wr"] * r["n"] for r in valid) / max(total_n, 1)
    annual = total_pnl / total_days * 365 if total_days else 0.0
    liq = sum(r["liquidations"] for r in valid)
    all_pos = all(period_results[p.name]["pnl_usd"] > 0 for p in PERIODS)
    short_n = sum(r["by_side"]["short"]["n"] for r in valid)
    long_n = sum(r["by_side"]["long"]["n"] for r in valid)
    max_dd = max((r["max_dd_usd"] for r in valid), default=0.0)
    weighted = {
        "n": total_n,
        "wr": round(weighted_wr, 4),
        "pnl_usd": round(total_pnl, 2),
        "annual_pnl_usd": round(annual, 2),
        "monthly_pnl_usd": round(annual / 12, 2),
        "all_periods_positive": all_pos,
        "liquidations": liq,
        "liq_rate": round(liq / total_n, 4) if total_n else 0.0,
        "long_n": long_n,
        "short_n": short_n,
        "max_period_dd_usd": round(max_dd, 2),
    }
    checks = {
        "n_>=_30": total_n >= 30,
        "wr_>=_60": weighted_wr >= 0.60,
        "annual_pnl_>=_100": annual >= 100,
        "all_periods_positive": all_pos,
        "liq_rate_<=_5pct": (liq / total_n if total_n else 1.0) <= 0.05,
    }
    return {
        "id": spec["id"],
        "desc": spec["desc"],
        "spec": spec,
        "periods": period_results,
        "weighted": weighted,
        "decision": {"checks": checks, "verdict": "PASS" if all(checks.values()) else "FAIL"},
    }


def main() -> None:
    print("G900 ensemble discovery starting...")
    t0 = time.time()
    specs = candidate_specs()
    period_caches: dict[str, dict[str, pd.DataFrame]] = {}
    for period in PERIODS:
        dfs = build_period_cache(period, "no_dead")
        add_btc_regime(dfs)
        period_caches[period.name] = dfs
        print(f"  loaded {period.name}: {len(dfs)} symbols")

    results = []
    for i, spec in enumerate(specs, 1):
        res = evaluate_spec(spec, period_caches)
        results.append(res)
        w = res["weighted"]
        print(
            f"{i:02d}/{len(specs)} {res['id']} {res['desc']:<32} "
            f"n={w['n']:>4} wr={w['wr']:.3f} ann={w['annual_pnl_usd']:>8.2f} "
            f"liq={w['liq_rate']:.3f} short={w['short_n']:>4} {res['decision']['verdict']}"
        )

    passers = [r for r in results if r["decision"]["verdict"] == "PASS"]
    ranked = sorted(
        results,
        key=lambda r: (
            r["decision"]["verdict"] == "PASS",
            r["weighted"]["annual_pnl_usd"],
            r["weighted"]["wr"],
            -r["weighted"]["liq_rate"],
        ),
        reverse=True,
    )
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cost_bps": COST_BPS,
        "equity": EQUITY,
        "n_specs": len(specs),
        "n_pass": len(passers),
        "top": ranked[:12],
        "results": results,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPASS {len(passers)}/{len(specs)}")
    print("Top candidates:")
    for r in ranked[:8]:
        w = r["weighted"]
        print(
            f"  {r['id']} {r['desc']}: n={w['n']} wr={w['wr']:.3f} "
            f"annual={w['annual_pnl_usd']:.2f} monthly={w['monthly_pnl_usd']:.2f} "
            f"liq={w['liq_rate']:.3f} long={w['long_n']} short={w['short_n']} "
            f"{r['decision']['verdict']}"
        )
    print(f"Wrote {OUT}")
    print(f"Elapsed {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
