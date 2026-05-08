"""Search CH1 variants that repair G7822's sparse-entry problem.

The G7822 search optimized for strict G1165 dominance, which left entry count
almost unchanged. This pass keeps the same CH1 event model, then ranks variants
that produce enough trades for faster paper observation while staying
liquidation-free and positive in every validation slice.
"""
from __future__ import annotations

import json
import math
import sys
import time
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g900_ensemble_discovery import (  # type: ignore
    PERIODS,
    EQUITY,
    add_btc_regime,
    build_period_cache,
    event_return,
)

OUT = SCRIPTS / "g7823_frequency_repair_results.json"

BASELINE_G1165 = {
    "id": "G1165",
    "n": 51,
    "wr": 0.6863,
    "pnl_usd": 825.43,
    "annual_pnl_usd": 193.13,
    "monthly_pnl_usd": 16.09,
    "liq_rate": 0.0,
    "max_period_dd_usd": 96.75,
    "all_periods_positive": True,
}

BASELINE_G7822 = {
    "id": "G7822",
    "n": 53,
    "wr": 0.6981,
    "pnl_usd": 1015.58,
    "annual_pnl_usd": 237.62,
    "monthly_pnl_usd": 19.80,
    "liq_rate": 0.0,
    "max_period_dd_usd": 92.88,
    "all_periods_positive": True,
}

SYMBOL_MODES = {
    "no_dead": {"exclude": {"WIFUSDT", "LTCUSDT", "BTCUSDT"}},
    "no_dead_no_weak": {
        "exclude": {"WIFUSDT", "LTCUSDT", "BTCUSDT", "MATICUSDT", "XRPUSDT", "LINKUSDT"}
    },
    "quality_rotators": {
        "include": {
            "AVAXUSDT",
            "BNBUSDT",
            "UNIUSDT",
            "ARBUSDT",
            "SUIUSDT",
            "DOGEUSDT",
            "ADAUSDT",
            "OPUSDT",
            "PEPEUSDT",
            "SOLUSDT",
            "DOTUSDT",
            "APTUSDT",
            "NEARUSDT",
        }
    },
    "liquid_alts": {
        "include": {
            "AVAXUSDT",
            "BNBUSDT",
            "SOLUSDT",
            "DOGEUSDT",
            "ADAUSDT",
            "ARBUSDT",
            "SUIUSDT",
            "OPUSDT",
            "PEPEUSDT",
            "NEARUSDT",
        }
    },
}

HOLDS = [24, 36, 48]
EXIT_PAIRS = [(0.10, 0.060), (0.12, 0.060), (0.14, 0.075), (0.16, 0.075)]
LEVERAGES = [8, 10]
PROFILES = [(8, 0.25), (8, 0.30), (10, 0.20), (10, 0.25)]


def fnum(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def symbol_ok(sym: str, mode: str) -> bool:
    rule = SYMBOL_MODES[mode]
    include = rule.get("include")
    exclude = rule.get("exclude", set())
    if include is not None and sym not in include:
        return False
    return sym not in exclude


def build_events() -> dict[str, list[dict[str, Any]]]:
    by_period: dict[str, list[dict[str, Any]]] = {}
    for period in PERIODS:
        dfs = build_period_cache(period, "no_dead")
        add_btc_regime(dfs)
        events: list[dict[str, Any]] = []
        for sym, df in dfs.items():
            base_mask = (df["ch1_score"] >= 76) & (df["atr_pct"] <= 12)
            for idx in np.where(base_mask.fillna(False).to_numpy(dtype=bool))[0]:
                for hold in HOLDS:
                    if idx + hold >= len(df):
                        continue
                    for tp, sl in EXIT_PAIRS:
                        for lev in LEVERAGES:
                            net_pct, liquidated, _ = event_return(df, idx, "long", hold, lev, tp, sl)
                            events.append(
                                {
                                    "ts": int(df.at[idx, "open_time"]),
                                    "exit_ts": int(df.at[idx, "open_time"]) + hold * 3600 * 1000,
                                    "sym": sym,
                                    "hold": hold,
                                    "tp": tp,
                                    "sl": sl,
                                    "lev": lev,
                                    "net_pct": float(net_pct),
                                    "liquidated": bool(liquidated),
                                    "score": fnum(df.at[idx, "ch1_score"]),
                                    "atr": fnum(df.at[idx, "atr_pct"]),
                                    "funding": fnum(df.at[idx, "funding_rate"], 0.0),
                                    "btc": fnum(df.at[idx, "btc_regime"], 0.0),
                                    "ret24": fnum(df.at[idx, "ret_24h"], 0.0),
                                    "vol": fnum(df.at[idx, "vol_ratio"], 1.0),
                                }
                            )
        by_period[period.name] = sorted(events, key=lambda e: (e["ts"], -e["score"]))
        print(f"  precomputed {period.name}: {len(events)} events", flush=True)
    return by_period


def pass_filter(ev: dict[str, Any], spec: dict[str, Any]) -> bool:
    return (
        ev["hold"] == spec["hold"]
        and ev["tp"] == spec["tp"]
        and ev["sl"] == spec["sl"]
        and ev["lev"] == spec["lev"]
        and symbol_ok(ev["sym"], spec["symbol_mode"])
        and ev["score"] >= spec["thr"]
        and spec["atr_min"] <= ev["atr"] <= spec["atr_max"]
        and (spec["max_funding"] is None or ev["funding"] <= spec["max_funding"])
        and (spec["min_btc"] is None or ev["btc"] >= spec["min_btc"])
        and (spec["max_ret24"] is None or ev["ret24"] <= spec["max_ret24"])
        and (spec["min_vol"] is None or ev["vol"] >= spec["min_vol"])
        and (spec["max_vol"] is None or ev["vol"] <= spec["max_vol"])
    )


def simulate_precomputed(events: list[dict[str, Any]], spec: dict[str, Any], days: int) -> dict[str, Any]:
    open_pos: list[tuple[int, str]] = []
    pnl = 0.0
    wins = 0
    liq = 0
    taken = 0
    curve = [0.0]
    by_symbol: dict[str, dict[str, Any]] = {}
    for ev in events:
        if not pass_filter(ev, spec):
            continue
        ts = ev["ts"]
        sym = ev["sym"]
        open_pos = [p for p in open_pos if p[0] > ts]
        if any(p[1] == sym for p in open_pos):
            continue
        if len(open_pos) >= spec["max_conc"]:
            continue
        trade_pnl = EQUITY * spec["size"] * ev["net_pct"]
        pnl += trade_pnl
        curve.append(pnl)
        taken += 1
        wins += int(trade_pnl > 0)
        liq += int(ev["liquidated"])
        item = by_symbol.setdefault(sym, {"n": 0, "pnl": 0.0, "wins": 0})
        item["n"] += 1
        item["pnl"] += trade_pnl
        item["wins"] += int(trade_pnl > 0)
        open_pos.append((ev["exit_ts"], sym))
    arr = np.array(curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = peak - arr
    return {
        "n": taken,
        "wr": wins / taken if taken else 0.0,
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / days * 365, 2) if days else 0.0,
        "monthly_pnl_usd": round(pnl / days * 30.4, 2) if days else 0.0,
        "trades_per_month": round(taken / days * 30.4, 2) if days else 0.0,
        "liquidations": liq,
        "liq_rate": liq / taken if taken else 0.0,
        "max_dd_usd": round(float(dd.max()) if len(dd) else 0.0, 2),
        "by_symbol": {
            sym: {"n": v["n"], "pnl": round(v["pnl"], 2), "wr": round(v["wins"] / v["n"], 4)}
            for sym, v in sorted(by_symbol.items())
        },
    }


def evaluate(spec: dict[str, Any], events_by_period: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    periods = {}
    for period in PERIODS:
        periods[period.name] = simulate_precomputed(events_by_period[period.name], spec, period.days)
    valid = [r for r in periods.values() if r["n"] > 0]
    n = sum(r["n"] for r in valid)
    pnl = sum(r["pnl_usd"] for r in valid)
    days = sum(p.days for p in PERIODS if periods[p.name]["n"] > 0)
    wr = sum(r["wr"] * r["n"] for r in valid) / max(n, 1)
    annual = pnl / days * 365 if days else 0.0
    liq = sum(r["liquidations"] for r in valid)
    maxdd = max((r["max_dd_usd"] for r in valid), default=0.0)
    all_pos = all(periods[p.name]["pnl_usd"] > 0 for p in PERIODS)
    min_period = min((periods[p.name]["pnl_usd"] for p in PERIODS), default=0.0)
    weighted = {
        "n": n,
        "wr": round(wr, 4),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(annual, 2),
        "monthly_pnl_usd": round(annual / 12, 2),
        "trades_per_month": round(n / days * 30.4, 2) if days else 0.0,
        "liquidations": liq,
        "liq_rate": round(liq / n, 4) if n else 0.0,
        "max_period_dd_usd": round(maxdd, 2),
        "all_periods_positive": all_pos,
        "min_period_pnl_usd": round(min_period, 2),
    }
    gates = {
        "n_ge_100": n >= 100,
        "n_ge_150": n >= 150,
        "trades_ge_2x_g7822": n >= BASELINE_G7822["n"] * 2,
        "wr_ge_60": wr >= 0.60,
        "pnl_gt_g7822": pnl > BASELINE_G7822["pnl_usd"],
        "annual_gt_g1165": annual > BASELINE_G1165["annual_pnl_usd"],
        "liq_free": liq == 0,
        "all_periods_positive": all_pos,
        "maxdd_le_2x_g7822": maxdd <= BASELINE_G7822["max_period_dd_usd"] * 2.0,
    }
    score = (
        annual
        + pnl * 0.08
        + n * 1.0
        + wr * 120.0
        + min_period * 0.25
        - maxdd * 0.45
    )
    frequency_score = (
        n * 2.0
        + annual * 0.35
        + pnl * 0.04
        + min_period * 0.20
        + wr * 80.0
        - maxdd * 0.35
    )
    return {
        "id": spec["id"],
        "family": "g7822_frequency_repair_ch1",
        "spec": spec,
        "periods": periods,
        "weighted": weighted,
        "gates": gates,
        "balanced_pass": all(
            gates[k]
            for k in (
                "n_ge_100",
                "wr_ge_60",
                "pnl_gt_g7822",
                "annual_gt_g1165",
                "liq_free",
                "all_periods_positive",
                "maxdd_le_2x_g7822",
            )
        ),
        "fast_observation_pass": all(
            gates[k]
            for k in (
                "n_ge_150",
                "wr_ge_60",
                "annual_gt_g1165",
                "liq_free",
                "all_periods_positive",
                "maxdd_le_2x_g7822",
            )
        ),
        "score": round(score, 4),
        "frequency_score": round(frequency_score, 4),
    }


def candidate_specs() -> list[dict[str, Any]]:
    out = []
    idx = 7823
    filter_profiles = [
        {"max_funding": None, "min_btc": None, "max_ret24": None, "min_vol": None, "max_vol": None},
        {"max_funding": 0.0008, "min_btc": None, "max_ret24": None, "min_vol": None, "max_vol": None},
    ]
    for (
        symbol_mode,
        thr,
        atr_band,
        profile,
        hold,
        exit_pair,
        max_conc,
        filters,
    ) in product(
        SYMBOL_MODES,
        [76, 78, 80],
        [(0.0, 8.0), (0.0, 10.0), (2.0, 8.0), (2.0, 10.0), (3.0, 8.0)],
        PROFILES,
        [12, 18, 24, 36, 48],
        EXIT_PAIRS,
        [5, 8],
        filter_profiles,
    ):
        atr_min, atr_max = atr_band
        lev, size = profile
        tp, sl = exit_pair
        out.append(
            {
                "id": f"G{idx}",
                "symbol_mode": symbol_mode,
                "max_conc": max_conc,
                "thr": thr,
                "atr_min": atr_min,
                "atr_max": atr_max,
                "lev": lev,
                "size": size,
                "hold": hold,
                "tp": tp,
                "sl": sl,
                **filters,
            }
        )
        idx += 1
    return out


def main() -> None:
    print("G7823 frequency repair search starting...", flush=True)
    t0 = time.time()
    events_by_period = build_events()
    specs = candidate_specs()
    print(f"  specs: {len(specs)}", flush=True)
    results = []
    balanced = []
    fast = []
    for i, spec in enumerate(specs, 1):
        res = evaluate(spec, events_by_period)
        results.append(res)
        if res["balanced_pass"]:
            balanced.append(res)
        if res["fast_observation_pass"]:
            fast.append(res)
        if i % 10000 == 0:
            best = max(results, key=lambda r: r["frequency_score"])
            w = best["weighted"]
            print(
                f"{i}/{len(specs)} balanced={len(balanced)} fast={len(fast)} "
                f"best_freq={best['id']} n={w['n']} tpm={w['trades_per_month']} "
                f"wr={w['wr']:.4f} pnl={w['pnl_usd']:.2f} ann={w['annual_pnl_usd']:.2f} "
                f"dd={w['max_period_dd_usd']:.2f}"
                ,
                flush=True,
            )

    top_balanced = sorted(balanced, key=lambda r: r["score"], reverse=True)[:50]
    top_fast = sorted(fast, key=lambda r: r["frequency_score"], reverse=True)[:50]
    positive_liqfree = [
        r
        for r in results
        if r["weighted"]["all_periods_positive"] and r["weighted"]["liquidations"] == 0
    ]
    n100_liqfree = [
        r
        for r in results
        if r["weighted"]["n"] >= 100 and r["weighted"]["liquidations"] == 0
    ]
    top_overall_frequency = sorted(results, key=lambda r: r["frequency_score"], reverse=True)[:100]
    top_overall_balanced = sorted(results, key=lambda r: r["score"], reverse=True)[:100]
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "baseline_g1165": BASELINE_G1165,
        "baseline_g7822": BASELINE_G7822,
        "n_specs": len(specs),
        "n_balanced_pass": len(balanced),
        "n_fast_observation_pass": len(fast),
        "n_positive_liqfree": len(positive_liqfree),
        "n100_liqfree": len(n100_liqfree),
        "top_balanced": top_balanced,
        "top_fast_observation": top_fast,
        "top_positive_by_trades": sorted(
            positive_liqfree,
            key=lambda r: (r["weighted"]["n"], r["score"]),
            reverse=True,
        )[:100],
        "top_n100_liqfree_by_score": sorted(n100_liqfree, key=lambda r: r["score"], reverse=True)[:100],
        "top_overall_frequency": top_overall_frequency,
        "top_overall_balanced": top_overall_balanced,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}", flush=True)
    print(f"Balanced pass: {len(balanced)}", flush=True)
    print(f"Fast observation pass: {len(fast)}", flush=True)
    print(f"Positive/liquidation-free: {len(positive_liqfree)}", flush=True)
    print(f"N>=100/liquidation-free: {len(n100_liqfree)}", flush=True)
    for label, rows in (("balanced", top_balanced[:6]), ("fast", top_fast[:6])):
        print(f"== {label} ==", flush=True)
        for res in rows:
            print(
                json.dumps(
                    {
                        "id": res["id"],
                        "weighted": res["weighted"],
                        "spec": res["spec"],
                        "score": res["score"],
                        "frequency_score": res["frequency_score"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    print(f"Elapsed {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
