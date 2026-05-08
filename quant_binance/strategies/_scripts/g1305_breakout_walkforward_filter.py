"""G1305 walk-forward filter validation for G4006 breakout-long.

G1304 found a non-CH1, zero-overlap watchlist candidate:

    G4006 breakout_long no_dead
    24h range breakout, 24h momentum >= 10%, vol_ratio >= 3,
    hold 36h, lev 8, size 20%, TP 6%, SL 8%.

The raw candidate missed strict promotion by a little, and diagnostics showed
symbol/hour concentration. This script tests whether filters chosen only from
past data improve the next period:

1. Train on OOS22-23 -> test OOS24-Q1
2. Train on OOS22-23 + OOS24-Q1 -> test IS25-26

It also reports in-sample diagnostic filters separately, but the walk-forward
result is the only evidence that matters for promotion.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(r"C:\Users\SSAFY\Desktop\first_repo")
SCRIPTS = ROOT / "quant_binance" / "strategies" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

from g900_ensemble_discovery import EQUITY, PERIODS, add_btc_regime, build_period_cache, event_return  # type: ignore
from g1303_non_ch1_overlap_search import breakout_events  # type: ignore

OUT = SCRIPTS / "g1305_breakout_walkforward_filter_results.json"

G4006 = {
    "family": "breakout_long",
    "univ": "no_dead",
    "max_conc": 5,
    "params": {
        "engine": "breakout_long",
        "hold": 36,
        "break_bps": 50,
        "mom_24h": 0.10,
        "vol_ratio": 3.0,
        "atr_min": 0,
        "atr_max": 8,
        "lev": 8,
        "size": 0.20,
        "tp_pct": 0.06,
        "sl_pct": 0.08,
        "btc_gate": None,
    },
}


def simulate_trades_for_period(period: Any) -> list[dict[str, Any]]:
    dfs = build_period_cache(period, G4006["univ"])
    add_btc_regime(dfs)
    events = [ev for ev in breakout_events(dfs, G4006["params"]) if ev["side"] == "long"]
    best: dict[tuple[int, str], dict[str, Any]] = {}
    for ev in events:
        key = (int(ev["ts"]), str(ev["sym"]))
        prev = best.get(key)
        if prev is None or ev["confidence"] > prev["confidence"]:
            best[key] = ev
    events = sorted(best.values(), key=lambda ev: (ev["ts"], -ev["confidence"]))

    open_pos: list[tuple[int, str]] = []
    trades: list[dict[str, Any]] = []
    for ev in events:
        ts = int(ev["ts"])
        sym = str(ev["sym"])
        open_pos = [p for p in open_pos if p[0] > ts]
        if any(p[1] == sym for p in open_pos):
            continue
        if len(open_pos) >= G4006["max_conc"]:
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
        pnl = EQUITY * ev["size"] * net_pct
        trades.append(
            {
                "period": period.name,
                "ts": ts,
                "hour": time.gmtime(ts / 1000).tm_hour,
                "symbol": sym,
                "pnl_usd": round(float(pnl), 8),
                "win": pnl > 0,
                "liquidated": bool(liquidated),
            }
        )
        open_pos.append((ts + ev["hold"] * 3600 * 1000, sym))
    return trades


def stats(trades: list[dict[str, Any]], *, days: int | None = None) -> dict[str, Any]:
    if not trades:
        return {
            "n": 0,
            "wr": 0.0,
            "pnl_usd": 0.0,
            "annual_pnl_usd": 0.0,
            "max_dd_usd": 0.0,
            "liquidations": 0,
        }
    pnl = sum(float(t["pnl_usd"]) for t in trades)
    wins = sum(1 for t in trades if t["win"])
    liq = sum(1 for t in trades if t["liquidated"])
    curve = [0.0]
    running = 0.0
    for t in sorted(trades, key=lambda item: int(item["ts"])):
        running += float(t["pnl_usd"])
        curve.append(running)
    peak = curve[0]
    max_dd = 0.0
    for val in curve:
        peak = max(peak, val)
        max_dd = max(max_dd, peak - val)
    if days is None:
        period_names = {t["period"] for t in trades}
        days = sum(p.days for p in PERIODS if p.name in period_names)
    annual = pnl / days * 365 if days else 0.0
    return {
        "n": len(trades),
        "wr": round(wins / len(trades), 4),
        "pnl_usd": round(pnl, 2),
        "annual_pnl_usd": round(annual, 2),
        "monthly_pnl_usd": round(annual / 12, 2),
        "max_dd_usd": round(max_dd, 2),
        "liquidations": liq,
        "liq_rate": round(liq / len(trades), 4),
    }


def group_stats(trades: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        groups.setdefault(str(trade[key]), []).append(trade)
    return {name: stats(rows) for name, rows in sorted(groups.items())}


def positive_values(
    train: list[dict[str, Any]],
    key: str,
    *,
    min_n: int,
    min_wr: float,
    min_pnl: float,
) -> set[str]:
    out = set()
    for name, st in group_stats(train, key).items():
        if st["n"] >= min_n and st["wr"] >= min_wr and st["pnl_usd"] > min_pnl:
            out.add(name)
    return out


def top_values(train: list[dict[str, Any]], key: str, *, top_n: int, min_n: int) -> set[str]:
    rows = [(name, st) for name, st in group_stats(train, key).items() if st["n"] >= min_n]
    rows.sort(key=lambda item: (item[1]["pnl_usd"], item[1]["wr"], item[1]["n"]), reverse=True)
    return {name for name, _st in rows[:top_n]}


def apply_filter(trades: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
    return [trade for trade in trades if predicate(trade)]


def build_filter_specs(train: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    pos_symbols = positive_values(train, "symbol", min_n=8, min_wr=0.55, min_pnl=0.0)
    pos_hours = positive_values(train, "hour", min_n=8, min_wr=0.55, min_pnl=0.0)
    top_symbols = top_values(train, "symbol", top_n=8, min_n=8)
    top_hours = top_values(train, "hour", top_n=8, min_n=8)
    return {
        "baseline": {"symbols": None, "hours": None},
        "positive_symbols": {"symbols": sorted(pos_symbols), "hours": None},
        "positive_hours": {"symbols": None, "hours": sorted(pos_hours)},
        "positive_symbols_and_hours": {"symbols": sorted(pos_symbols), "hours": sorted(pos_hours)},
        "top8_symbols": {"symbols": sorted(top_symbols), "hours": None},
        "top8_hours": {"symbols": None, "hours": sorted(top_hours)},
        "top8_symbols_and_hours": {"symbols": sorted(top_symbols), "hours": sorted(top_hours)},
    }


def filter_predicate(spec: dict[str, Any]) -> Callable[[dict[str, Any]], bool]:
    symbols = None if spec["symbols"] is None else {str(s) for s in spec["symbols"]}
    hours = None if spec["hours"] is None else {int(h) for h in spec["hours"]}

    def predicate(trade: dict[str, Any]) -> bool:
        if symbols is not None and str(trade["symbol"]) not in symbols:
            return False
        if hours is not None and int(trade["hour"]) not in hours:
            return False
        return True

    return predicate


def main() -> None:
    print("G1305 breakout walk-forward filter validation starting...")
    by_period = {period.name: simulate_trades_for_period(period) for period in PERIODS}
    all_trades = [trade for rows in by_period.values() for trade in rows]
    print(f"  baseline trades: {len(all_trades)}")

    folds = [
        {
            "name": "train_OOS22_test_OOS24",
            "train_periods": ["OOS22-23"],
            "test_periods": ["OOS24-Q1"],
        },
        {
            "name": "train_OOS22_OOS24_test_IS25",
            "train_periods": ["OOS22-23", "OOS24-Q1"],
            "test_periods": ["IS25-26"],
        },
    ]

    fold_results = []
    strategy_names = set()
    for fold in folds:
        train = [t for p in fold["train_periods"] for t in by_period[p]]
        test = [t for p in fold["test_periods"] for t in by_period[p]]
        filter_specs = build_filter_specs(train)
        fold_record = {
            **fold,
            "train_stats": stats(train),
            "test_baseline_stats": stats(test),
            "filter_specs": filter_specs,
            "results": {},
        }
        for name, spec in filter_specs.items():
            strategy_names.add(name)
            pred = filter_predicate(spec)
            train_filtered = apply_filter(train, pred)
            test_filtered = apply_filter(test, pred)
            fold_record["results"][name] = {
                "train": stats(train_filtered),
                "test": stats(test_filtered),
            }
        fold_results.append(fold_record)

    aggregate: dict[str, Any] = {}
    for name in sorted(strategy_names):
        test_rows = []
        by_fold = {}
        for fold in fold_results:
            spec = fold["filter_specs"][name]
            pred = filter_predicate(spec)
            fold_test = [t for p in fold["test_periods"] for t in by_period[p]]
            selected = apply_filter(fold_test, pred)
            test_rows.extend(selected)
            by_fold[fold["name"]] = stats(selected)
        total_days = sum(p.days for p in PERIODS if p.name in {"OOS24-Q1", "IS25-26"})
        agg_stats = stats(test_rows, days=total_days)
        checks = {
            "n_>=_30": agg_stats["n"] >= 30,
            "wr_>=_55": agg_stats["wr"] >= 0.55,
            "annual_>=_80": agg_stats["annual_pnl_usd"] >= 80,
            "all_test_folds_positive": all(v["pnl_usd"] > 0 for v in by_fold.values()),
            "liq_==_0": agg_stats["liquidations"] == 0,
            "dd_<=_150": agg_stats["max_dd_usd"] <= 150,
        }
        aggregate[name] = {
            "test_stats": agg_stats,
            "by_fold": by_fold,
            "checks": checks,
            "verdict": "PASS" if all(checks.values()) else "FAIL",
        }

    in_sample_filters = build_filter_specs(all_trades)
    diagnostics = {
        "by_symbol": group_stats(all_trades, "symbol"),
        "by_hour": group_stats(all_trades, "hour"),
        "in_sample_filter_specs": in_sample_filters,
        "in_sample_filtered": {
            name: stats(apply_filter(all_trades, filter_predicate(spec)))
            for name, spec in in_sample_filters.items()
        },
    }

    payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "strategy": G4006,
        "baseline_all_periods": stats(all_trades),
        "baseline_by_period": {name: stats(rows) for name, rows in by_period.items()},
        "folds": fold_results,
        "aggregate_oos": aggregate,
        "diagnostics": diagnostics,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nAggregate walk-forward OOS:")
    for name, rec in sorted(aggregate.items(), key=lambda item: item[1]["test_stats"]["pnl_usd"], reverse=True):
        st = rec["test_stats"]
        fails = [k for k, v in rec["checks"].items() if not v]
        print(
            f"  {name:28s} {rec['verdict']} n={st['n']:>3} wr={st['wr']:.3f} "
            f"pnl={st['pnl_usd']:>8.2f} ann={st['annual_pnl_usd']:>7.2f} "
            f"dd={st['max_dd_usd']:>7.2f} fails={','.join(fails) if fails else '-'}"
        )
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
