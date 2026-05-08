"""Search for a G1165 replacement that dominates the baseline.

The acceptance gate is intentionally stricter than the original G915 search:
the selected candidate must beat G1165 on activity, win rate, total PnL,
annual/monthly PnL, drawdown, liquidation rate, and period consistency.
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
    make_event,
    simulate,
)

OUT = SCRIPTS / "g1166_g1165_dominance_results.json"

BASELINE = {
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

SYMBOL_MODES = {
    "no_dead": None,
    "no_dead_no_weak_legacy": {"exclude": {"MATICUSDT", "XRPUSDT", "LTCUSDT", "WIFUSDT", "BTCUSDT"}},
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
    "alt_liquid_large": {
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


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def filtered_dfs(dfs: dict[str, Any], mode: str) -> dict[str, Any]:
    rule = SYMBOL_MODES[mode]
    if not rule:
        return dfs
    include = rule.get("include")
    exclude = rule.get("exclude", set())
    out = {}
    for sym, df in dfs.items():
        if include is not None and sym not in include:
            continue
        if sym in exclude:
            continue
        out[sym] = df
    return out


def enhanced_ch1_events(dfs: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sym, df in dfs.items():
        mask = (
            (df["ch1_score"] >= spec["thr"])
            & (df["atr_pct"] >= spec["atr_min"])
            & (df["atr_pct"] <= spec["atr_max"])
        )
        if spec.get("max_funding") is not None:
            mask = mask & (df["funding_rate"].isna() | (df["funding_rate"] <= spec["max_funding"]))
        if spec.get("min_btc_regime") is not None:
            mask = mask & (df["btc_regime"] >= spec["min_btc_regime"])
        if spec.get("max_btc_regime") is not None:
            mask = mask & (df["btc_regime"] <= spec["max_btc_regime"])
        if spec.get("min_ret_24h") is not None:
            mask = mask & (df["ret_24h"] >= spec["min_ret_24h"])
        if spec.get("max_ret_24h") is not None:
            mask = mask & (df["ret_24h"] <= spec["max_ret_24h"])
        if spec.get("min_vol_ratio") is not None:
            mask = mask & (df["vol_ratio"] >= spec["min_vol_ratio"])
        if spec.get("max_vol_ratio") is not None:
            mask = mask & (df["vol_ratio"] <= spec["max_vol_ratio"])

        idxs = np.where(mask.fillna(False).to_numpy(dtype=bool))[0]
        for idx in idxs:
            if idx + spec["hold"] >= len(df):
                continue
            score = float(df.at[idx, "ch1_score"])
            vr = float(df.at[idx, "vol_ratio"]) if finite(df.at[idx, "vol_ratio"]) else 1.0
            conf = 1.0 + max(0.0, score - spec["thr"]) / 20.0 + min(0.5, max(0.0, vr - 1.0) / 8.0)
            out.append(
                make_event(
                    df.at[idx, "open_time"],
                    sym,
                    idx,
                    "long",
                    spec["engine"],
                    spec["hold"],
                    spec["lev"],
                    spec["size"],
                    conf,
                    spec.get("tp_pct"),
                    spec.get("sl_pct"),
                )
            )
    return out


def metrics_for(spec: dict[str, Any], period_caches: dict[str, dict[str, Any]]) -> dict[str, Any]:
    periods: dict[str, Any] = {}
    for period in PERIODS:
        dfs = filtered_dfs(period_caches[period.name], spec["symbol_mode"])
        events = enhanced_ch1_events(dfs, spec)
        periods[period.name] = simulate(events, dfs, spec["max_conc"], period.days)

    valid = [r for r in periods.values() if r["n"] > 0]
    total_n = sum(r["n"] for r in valid)
    total_pnl = sum(r["pnl_usd"] for r in valid)
    total_days = sum(p.days for p in PERIODS if periods[p.name]["n"] > 0)
    wr = sum(r["wr"] * r["n"] for r in valid) / max(total_n, 1)
    annual = total_pnl / total_days * 365 if total_days else 0.0
    liq = sum(r["liquidations"] for r in valid)
    max_dd = max((r["max_dd_usd"] for r in valid), default=0.0)
    all_pos = all(periods[p.name]["pnl_usd"] > 0 for p in PERIODS)
    min_period_pnl = min((periods[p.name]["pnl_usd"] for p in PERIODS), default=0.0)

    weighted = {
        "n": total_n,
        "wr": round(wr, 4),
        "pnl_usd": round(total_pnl, 2),
        "annual_pnl_usd": round(annual, 2),
        "monthly_pnl_usd": round(annual / 12, 2),
        "liquidations": liq,
        "liq_rate": round(liq / total_n, 4) if total_n else 0.0,
        "max_period_dd_usd": round(max_dd, 2),
        "all_periods_positive": all_pos,
        "min_period_pnl_usd": round(min_period_pnl, 2),
    }
    checks = {
        "n_gt_g1165": total_n > BASELINE["n"],
        "wr_gt_g1165": wr > BASELINE["wr"],
        "pnl_gt_g1165": total_pnl > BASELINE["pnl_usd"],
        "annual_gt_g1165": annual > BASELINE["annual_pnl_usd"],
        "monthly_gt_g1165": annual / 12 > BASELINE["monthly_pnl_usd"],
        "maxdd_lt_g1165": max_dd < BASELINE["max_period_dd_usd"],
        "liq_eq_g1165": liq == 0,
        "all_periods_positive": all_pos,
    }
    score = (
        annual * 1.0
        + total_pnl * 0.15
        + wr * 120.0
        + min_period_pnl * 0.3
        - max_dd * 0.8
        + total_n * 0.15
    )
    return {
        "id": spec["id"],
        "family": "g1165_dominance_ch1_filter",
        "spec": spec,
        "periods": periods,
        "weighted": weighted,
        "checks": checks,
        "dominates_g1165": all(checks.values()),
        "score": round(score, 4),
    }


def specs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    idx = 1166
    coarse_specs: list[dict[str, Any]] = []
    for (
        symbol_mode,
        thr,
        hold,
        atr_band,
        profile,
        exit_pair,
    ) in product(
        SYMBOL_MODES,
        [76, 80, 82, 84],
        [24, 36, 48],
        [(0.0, 8.0), (0.0, 10.0), (3.0, 8.0), (3.0, 10.0)],
        [
            {"lev": 8, "size": 0.30},
            {"lev": 10, "size": 0.25},
            {"lev": 12, "size": 0.30},
        ],
        [(0.10, 0.060), (0.12, 0.060), (0.14, 0.075), (0.16, 0.075)],
    ):
        atr_min, atr_max = atr_band
        tp_pct, sl_pct = exit_pair
        coarse_specs.append(
            {
                "id": "",
                "engine": "ch1_quality_dominance",
                "symbol_mode": symbol_mode,
                "max_conc": 5,
                "thr": thr,
                "hold": hold,
                "atr_min": atr_min,
                "atr_max": atr_max,
                "lev": profile["lev"],
                "size": profile["size"],
                "tp_pct": tp_pct,
                "sl_pct": sl_pct,
                "max_funding": None,
                "min_btc_regime": None,
                "max_btc_regime": None,
                "min_ret_24h": None,
                "max_ret_24h": None,
                "min_vol_ratio": None,
                "max_vol_ratio": None,
            }
        )

    for base in coarse_specs:
        variants = [base]
        for max_funding, min_btc, max_ret, min_vol, max_vol in product(
            [0.0008],
            [0.0],
            [0.30, None],
            [1.0, None],
            [6.0, None],
        ):
            clone = dict(base)
            clone.update(
                {
                    "max_funding": max_funding,
                    "min_btc_regime": min_btc,
                    "max_ret_24h": max_ret,
                    "min_vol_ratio": min_vol,
                    "max_vol_ratio": max_vol,
                }
            )
            variants.append(clone)
        for spec in variants:
            spec["id"] = f"G{idx}"
            out.append(spec)
            idx += 1
    return out


def main() -> None:
    print("G1166 dominance search starting...")
    t0 = time.time()
    period_caches: dict[str, dict[str, Any]] = {}
    for period in PERIODS:
        dfs = build_period_cache(period, "no_dead")
        add_btc_regime(dfs)
        period_caches[period.name] = dfs
        print(f"  loaded {period.name}: {len(dfs)} symbols")

    all_specs = specs()
    print(f"  specs: {len(all_specs)}")
    results: list[dict[str, Any]] = []
    dominators: list[dict[str, Any]] = []
    for i, spec in enumerate(all_specs, 1):
        res = metrics_for(spec, period_caches)
        results.append(res)
        if res["dominates_g1165"]:
            dominators.append(res)
            w = res["weighted"]
            print(
                f"DOM {res['id']} n={w['n']} wr={w['wr']:.4f} pnl={w['pnl_usd']:.2f} "
                f"ann={w['annual_pnl_usd']:.2f} dd={w['max_period_dd_usd']:.2f} "
                f"mode={spec['symbol_mode']} thr={spec['thr']} hold={spec['hold']} "
                f"atr={spec['atr_min']}-{spec['atr_max']} lev={spec['lev']} size={spec['size']} "
                f"tp={spec['tp_pct']} sl={spec['sl_pct']} fund={spec['max_funding']} "
                f"btc={spec['min_btc_regime']} maxret={spec['max_ret_24h']} "
                f"vol={spec['min_vol_ratio']}-{spec['max_vol_ratio']}"
            )
        elif i % 5000 == 0:
            best = max(results, key=lambda r: r["score"])
            w = best["weighted"]
            print(
                f"{i}/{len(all_specs)} best={best['id']} n={w['n']} wr={w['wr']:.4f} "
                f"pnl={w['pnl_usd']:.2f} ann={w['annual_pnl_usd']:.2f} "
                f"dd={w['max_period_dd_usd']:.2f} dom={len(dominators)}"
            )

    ranked = sorted(results, key=lambda r: (r["dominates_g1165"], r["score"]), reverse=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "baseline": BASELINE,
        "n_specs": len(all_specs),
        "n_dominators": len(dominators),
        "top_dominators": sorted(dominators, key=lambda r: r["score"], reverse=True)[:50],
        "top_overall": ranked[:100],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"Dominators: {len(dominators)}")
    for res in payload["top_dominators"][:10] or payload["top_overall"][:10]:
        w = res["weighted"]
        s = res["spec"]
        print(
            f"{res['id']} dom={res['dominates_g1165']} score={res['score']} n={w['n']} "
            f"wr={w['wr']:.4f} pnl={w['pnl_usd']:.2f} ann={w['annual_pnl_usd']:.2f} "
            f"mo={w['monthly_pnl_usd']:.2f} dd={w['max_period_dd_usd']:.2f} "
            f"liq={w['liq_rate']:.4f} mode={s['symbol_mode']} thr={s['thr']} hold={s['hold']} "
            f"atr={s['atr_min']}-{s['atr_max']} lev={s['lev']} size={s['size']} "
            f"tp={s['tp_pct']} sl={s['sl_pct']}"
        )
    print(f"Elapsed {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
