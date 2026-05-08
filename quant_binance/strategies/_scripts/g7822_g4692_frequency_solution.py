"""Evaluate the G7822 + G4692 paper-observation bundle.

G7822 is the quality CH1 replacement for G1165, but it is sparse. G4692 is a
non-CH1 watch-confirm breakout sleeve with much higher cadence. This script
checks the combined observation frequency and direct timestamp/symbol overlap.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g1300_two_slot_search import simulate_with_keys  # type: ignore
from g1309_watch_confirm_breakout_search import simulate as simulate_breakout  # type: ignore
from g1309_watch_confirm_breakout_search import watch_confirm_events  # type: ignore
from g900_ensemble_discovery import PERIODS, add_btc_regime, build_period_cache, ch1_events  # type: ignore

OUT = SCRIPTS / "g7822_g4692_frequency_solution_results.json"

G7822_EXCLUDED = {"WIFUSDT", "LTCUSDT", "BTCUSDT", "MATICUSDT", "XRPUSDT", "LINKUSDT"}

G7822_SPEC = {
    "id": "G7822",
    "desc": "quality CH1 replacement for G1165",
    "univ": "no_dead_no_weak",
    "max_conc": 5,
    "engine": {
        "thr": 80,
        "hold": 48,
        "atr_min": 2,
        "atr_max": 8,
        "lev": 8,
        "size": 0.30,
        "tp_pct": 0.16,
        "sl_pct": 0.075,
    },
}

G4692_SPEC = {
    "id": "G4692",
    "desc": "watch-confirm breakout strict_plus_confirm w_break30_ret8_vol25 c1_strict mid",
    "mode": "strict_plus_confirm",
    "strict_trade": {
        "hold": 36,
        "lev": 8.0,
        "size": 0.20,
        "tp_pct": 0.06,
        "sl_pct": 0.08,
    },
    "confirm_trade": {
        "hold": 24,
        "lev": 7.0,
        "size": 0.16,
        "tp_pct": 0.05,
        "sl_pct": 0.065,
    },
    "watch": {
        "break_bps": 30,
        "min_ret_24h": 0.08,
        "min_vol_ratio": 2.5,
    },
    "confirm": {
        "max_lag_bars": 1,
        "confirm_break_bps": 50,
        "min_follow_bps": 0,
        "min_ret_24h": 0.10,
        "min_vol_ratio": 3.0,
        "failure_bps": 0,
    },
}


def strip_keys(result: dict[str, Any]) -> tuple[dict[str, Any], set[tuple[str, int, str, str]]]:
    keys = set(map(tuple, result.pop("keys")))
    return result, keys


def weighted(periods: dict[str, dict[str, Any]]) -> dict[str, Any]:
    valid = [periods[p.name] for p in PERIODS if periods[p.name]["n"] > 0]
    n = sum(r["n"] for r in valid)
    pnl = sum(r["pnl_usd"] for r in valid)
    days = sum(p.days for p in PERIODS if periods[p.name]["n"] > 0)
    wr = sum(r["wr"] * r["n"] for r in valid) / max(n, 1)
    liq = sum(r["liquidations"] for r in valid)
    def dd_value(row: dict[str, Any]) -> float:
        return float(row.get("max_dd_usd", row.get("max_dd_usd_individual_max", 0.0)))

    max_dd = max((dd_value(r) for r in valid), default=0.0)
    min_pnl = min((periods[p.name]["pnl_usd"] for p in PERIODS), default=0.0)
    return {
        "n": n,
        "trades_per_month": round(n / days * 30.4, 2) if days else 0.0,
        "wr": round(wr, 4),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(pnl / days * 365, 2) if days else 0.0,
        "monthly_pnl_usd": round((pnl / days * 365) / 12, 2) if days else 0.0,
        "all_periods_positive": all(periods[p.name]["pnl_usd"] > 0 for p in PERIODS),
        "min_period_pnl_usd": round(min_pnl, 2),
        "liquidations": liq,
        "liq_rate": round(liq / max(n, 1), 4) if n else 0.0,
        "max_period_dd_usd": round(max_dd, 2),
    }


def combine_periods(a: dict[str, Any], b: dict[str, Any]) -> dict[str, dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}
    for period in PERIODS:
        ra = a[period.name]
        rb = b[period.name]
        n = ra["n"] + rb["n"]
        pnl = ra["pnl_usd"] + rb["pnl_usd"]
        wins = ra["wr"] * ra["n"] + rb["wr"] * rb["n"]
        combined[period.name] = {
            "n": n,
            "trades_per_month": round(n / period.days * 30.4, 2),
            "wr": round(wins / max(n, 1), 4),
            "pnl_usd": round(pnl, 2),
            "annual_pnl_usd": round(pnl / period.days * 365, 2),
            "monthly_pnl_usd": round(pnl / period.days * 30.4, 2),
            "liquidations": ra["liquidations"] + rb["liquidations"],
            "liq_rate": round((ra["liquidations"] + rb["liquidations"]) / max(n, 1), 4),
            "max_dd_usd_individual_max": max(ra["max_dd_usd"], rb["max_dd_usd"]),
            "max_dd_usd_slot_sum_upper_bound": round(ra["max_dd_usd"] + rb["max_dd_usd"], 2),
            "components": {
                "G7822": {
                    "n": ra["n"],
                    "wr": round(ra["wr"], 4),
                    "pnl_usd": ra["pnl_usd"],
                    "max_dd_usd": ra["max_dd_usd"],
                },
                "G4692": {
                    "n": rb["n"],
                    "wr": round(rb["wr"], 4),
                    "pnl_usd": rb["pnl_usd"],
                    "max_dd_usd": rb["max_dd_usd"],
                },
            },
        }
    return combined


def main() -> None:
    print("G7822+G4692 frequency solution evaluation starting...", flush=True)
    t0 = time.time()
    g7822_periods: dict[str, dict[str, Any]] = {}
    g4692_periods: dict[str, dict[str, Any]] = {}
    g7822_keys: set[tuple[str, int, str, str]] = set()
    g4692_keys: set[tuple[str, int, str, str]] = set()

    for period in PERIODS:
        dfs = build_period_cache(period, "no_dead")
        add_btc_regime(dfs)
        g7822_dfs = {sym: df for sym, df in dfs.items() if sym not in G7822_EXCLUDED}

        ch1 = ch1_events(g7822_dfs, G7822_SPEC["engine"])
        g7822_res, keys = strip_keys(
            simulate_with_keys(ch1, g7822_dfs, G7822_SPEC["max_conc"], period.days, period.name)
        )
        g7822_periods[period.name] = g7822_res
        g7822_keys.update(keys)

        breakout = watch_confirm_events(dfs, G4692_SPEC)
        g4692_res, keys = strip_keys(simulate_breakout(breakout, dfs, 5, period.days, period.name))
        g4692_periods[period.name] = g4692_res
        g4692_keys.update(keys)

        print(
            f"  {period.name}: G7822 n={g7822_res['n']} G4692 n={g4692_res['n']} "
            f"combined={g7822_res['n'] + g4692_res['n']}",
            flush=True,
        )

    combined_periods = combine_periods(g7822_periods, g4692_periods)
    combined_weighted = weighted(combined_periods)
    overlap = g7822_keys & g4692_keys
    union = g7822_keys | g4692_keys

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "question": "Does pairing G7822 with G4692 solve paper-entry frequency while preserving G7822 quality?",
        "interpretation": "Slot-sum paper observation bundle, not a single shared-equity execution simulation.",
        "components": {
            "G7822": {
                "role": "quality CH1 replacement/shadow for G1165",
                "spec": G7822_SPEC,
                "periods": g7822_periods,
                "weighted": weighted(g7822_periods),
            },
            "G4692": {
                "role": "high-frequency non-CH1 paper-observation sleeve",
                "spec": G4692_SPEC,
                "periods": g4692_periods,
                "weighted": weighted(g4692_periods),
            },
        },
        "combined": {
            "periods": combined_periods,
            "weighted": combined_weighted,
            "direct_entry_overlap": {
                "n": len(overlap),
                "jaccard": round(len(overlap) / max(len(union), 1), 6),
                "g7822_cover": round(len(overlap) / max(len(g7822_keys), 1), 6),
                "g4692_cover": round(len(overlap) / max(len(g4692_keys), 1), 6),
            },
            "frequency_gate": {
                "target_trades_per_month": 4.0,
                "actual_trades_per_month": combined_weighted["trades_per_month"],
                "passes": combined_weighted["trades_per_month"] >= 4.0,
            },
            "quality_gate": {
                "all_periods_positive": combined_weighted["all_periods_positive"],
                "liquidations": combined_weighted["liquidations"],
                "passes": combined_weighted["all_periods_positive"] and combined_weighted["liquidations"] == 0,
            },
        },
        "decision": {
            "verdict": "PASS" if combined_weighted["trades_per_month"] >= 4.0 and combined_weighted["all_periods_positive"] and combined_weighted["liquidations"] == 0 else "FAIL",
            "recommendation": "Paper-observe G7822 and G4692 together. Keep G7822 unchanged; use G4692 for cadence.",
        },
        "elapsed_sec": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    print(json.dumps(payload["combined"]["weighted"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
