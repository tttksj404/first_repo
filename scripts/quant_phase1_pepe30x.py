#!/usr/bin/env python3
"""Phase 1: Replicate PEPE 30x live strategy + variants.

Live config (from strategy_override.approved.json):
  - universe: PEPEUSDT
  - lev: 30, margin_pct: 0.4 (per_trade_equity_risk)
  - tp_roe: 32%, sl_roe: -10% (turnaround style)
  - long_only_turnaround_mode
  - max_holding 4320 min = 72h
  - b3_msb: ATR breakout (atr_tp_multiple=4.2, atr_sl=2.8)

Test variants:
  V1: PEPE 30x momentum mom168 lev30 tp32% sl10% hold72 (long+short)
  V2: PEPE 30x ATR breakout (b3_msb-like) atr_tp4.2 atr_sl2.8 hold72
  V3: PEPE 30x turnaround long-only (rsi<25 bounce) tp32 sl10 hold72
  V4: Same as V1 but lev15 (definitive_hantang baseline)
  V5: Same as V1 but lev10 (more conservative)
  V6: Same as V1 but lev45 (more aggressive)
  V7: Same as V1 but margin_pct=1.0 (full equity)
  V8: V1 + Bonferroni-grid: tp range 100-200, sl range 3-7

Output: quant_runtime/master_engine_runs/phase1_pepe30x.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_master_engine import (  # type: ignore
    StratParams, load_1h, compute_indicators, collect_trades,
    aggregate, mc_ruin, run_strategy, UNIVERSES, OUT_DIR, EQUITY,
)


def main():
    t0 = time.time()
    # Load PEPE
    arr = load_1h("PEPEUSDT")
    if arr is None:
        print("PEPEUSDT data missing"); sys.exit(1)
    ind = compute_indicators(arr)
    n_bars = len(arr)
    print(f"PEPE 1h × {n_bars} bars loaded in {time.time()-t0:.1f}s")

    variants = {
        "V1_momentum_lv30": StratParams(
            name="momentum", lev=30, margin_pct=0.4,
            tp_roe=32.0, sl_roe=-10.0, hold=72,
            mom_min=0.03, adx_min=4, long_only=False, cooldown_bars=2,
        ),
        "V2_atr_breakout_lv30": StratParams(
            name="atr_breakout", lev=30, margin_pct=0.4,
            tp_atr=4.2, sl_atr=2.8, hold=72,
            adx_min=4, breakout_atr_buf=0.0017, long_only=False,
        ),
        "V3_turnaround_long_lv30": StratParams(
            name="turnaround", lev=30, margin_pct=0.4,
            tp_roe=32.0, sl_roe=-10.0, hold=72,
            long_only=True, cooldown_bars=2,
        ),
        "V4_momentum_lv15": StratParams(
            name="momentum", lev=15, margin_pct=0.5,
            tp_roe=150.0, sl_roe=-5.0, hold=72,
            mom_min=0.03, adx_min=4, long_only=False,
        ),
        "V5_momentum_lv10": StratParams(
            name="momentum", lev=10, margin_pct=0.5,
            tp_roe=32.0, sl_roe=-10.0, hold=72,
            mom_min=0.03, adx_min=4, long_only=False,
        ),
        "V6_momentum_lv45": StratParams(
            name="momentum", lev=45, margin_pct=0.4,
            tp_roe=32.0, sl_roe=-10.0, hold=72,
            mom_min=0.03, adx_min=4, long_only=False,
        ),
        "V7_momentum_lv30_full_margin": StratParams(
            name="momentum", lev=30, margin_pct=1.0,
            tp_roe=32.0, sl_roe=-10.0, hold=72,
            mom_min=0.03, adx_min=4, long_only=False,
        ),
        "V8_momentum_lv30_long_only": StratParams(
            name="momentum", lev=30, margin_pct=0.4,
            tp_roe=32.0, sl_roe=-10.0, hold=72,
            mom_min=0.03, adx_min=4, long_only=True,
        ),
    }

    results = {}
    print()
    print(f"{'Variant':<35s} {'N':>4s} {'WR':>6s} {'PF':>6s} {'PnL$':>10s} {'%/yr':>9s} {'maxDD':>8s} {'ruin%':>6s}")
    print("=" * 105)
    for vid, p in variants.items():
        trades = collect_trades("PEPEUSDT", ind, p, 0, n_bars)
        agg = aggregate(trades)
        if agg["n"] == 0:
            print(f"{vid:<35s} {'-':>4s} {'-':>6s} {'-':>6s} {'-':>10s} {'-':>9s} {'-':>8s} {'-':>6s}")
            results[vid] = {"params": p.__dict__, "n_trades": 0}
            continue
        ruin = mc_ruin(trades)
        # 5bps slip
        p5 = StratParams(**{**p.__dict__, "extra_bps": 5.0})
        trades5 = collect_trades("PEPEUSDT", ind, p5, 0, n_bars)
        agg5 = aggregate(trades5)
        # 10bps slip
        p10 = StratParams(**{**p.__dict__, "extra_bps": 10.0})
        trades10 = collect_trades("PEPEUSDT", ind, p10, 0, n_bars)
        agg10 = aggregate(trades10)

        # WF 4-fold
        wf_pass = 0
        fold_size = n_bars // 4
        wf_folds = []
        for k in range(4):
            te_start = k * fold_size
            te_end = min((k + 1) * fold_size, n_bars)
            tr_fold = collect_trades("PEPEUSDT", ind, p, te_start, te_end)
            a = aggregate(tr_fold)
            wf_folds.append({"fold": k, "n": a["n"], "total": a["total_pnl"]})
            if a["total_pnl"] > 0:
                wf_pass += 1

        rec = {
            "params": p.__dict__,
            "agg": agg,
            "ruin": ruin,
            "slip_5bps": agg5,
            "slip_10bps": agg10,
            "wf_pass": wf_pass,
            "wf_folds": wf_folds,
        }
        results[vid] = rec
        pf_s = f"{agg['pf']:.2f}" if agg["pf"] is not None else "inf"
        print(f"{vid:<35s} {agg['n']:>4d} {agg['wr']*100:>5.1f}% {pf_s:>6s} ${agg['total_pnl']:>+8.2f} {agg['annual_pct']:>+8.1f}% ${agg['max_dd']:>6.2f} {ruin['ruin_pct']:>5.1f}%")
        print(f"{'':<35s}      slip5={agg5['total_pnl']:+.2f}  slip10={agg10['total_pnl']:+.2f}  WF={wf_pass}/4  med_final=${ruin['median_final']:.2f}  p5_min_eq=${ruin['p5_min_eq']:.2f}")

    out_path = OUT_DIR / "phase1_pepe30x.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print()
    print(f"\nElapsed: {time.time()-t0:.1f}s, saved: {out_path}")


if __name__ == "__main__":
    main()
