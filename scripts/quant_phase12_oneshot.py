#!/usr/bin/env python3
"""Phase 12: 한탕주의 (one-shot big-hit) 분석.

30x lev × $50 = $1500 notional. 가격이 3.33% 움직이면 ROE=100% (+$50, double).
가격이 6.67% 움직이면 ROE=200% (+$100, triple).
가격이 -3.33% 움직이면 ROE=-100% (wipe out).

질문:
  - 어느 종목/신호가 한 트레이드에서 "100% ROE 이상 hit" 확률이 가장 높은가?
  - 어느 신호가 entry → +200%/+300%/+500% ROE까지 도달하기 전에 SL을 안 맞나?
  - 평균 win size, 최대 win size, 한 방 기대값?

운영 시나리오:
  A) 한방: TP=200% ROE, SL=-50% ROE (entry 한 번, 큰 한 방 노림)
  B) 두탕: TP=500% ROE, SL=-30% ROE (3.33% 가격 SL → 16.67% 가격 TP)
  C) 세탕: TP=1000% ROE, SL=-20% ROE (도박)
"""
from __future__ import annotations

import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from quant_rotation_engine import (  # type: ignore
    RotationParams, aggregate, mc_ruin, load_1h, compute_indicators,
    rotation_backtest, PRIORITY_UNIVERSES, EQUITY, SIGNALS, COST_RT, Trade,
)
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "quant_runtime" / "master_engine_runs" / "phase12_oneshot.json"


def big_hit_analysis(priority, cache, sig_name, lev, margin_pct, tp_roe, sl_roe, hold_h, long_only):
    """Run with given config, then analyze per-trade ROE distribution."""
    p = RotationParams(signal=sig_name, long_only=long_only, lev=lev, margin_pct=margin_pct,
                       tp_roe=tp_roe, sl_roe=sl_roe, abort_roe=min(sl_roe-5, -50),
                       hold_h=hold_h, use_atr_exit=False)
    n = min(len(cache[s]["close"]) for s in priority if s in cache)
    trades = rotation_backtest(priority, cache, p, 200, n)
    if not trades:
        return None
    roes = np.array([t.roe_pct for t in trades])
    pnls = np.array([t.pnl_usd for t in trades])
    wins_100 = np.sum(roes >= 100)   # 더블+ 트레이드 횟수
    wins_200 = np.sum(roes >= 200)   # 트리플+
    wins_500 = np.sum(roes >= 500)   # 6배+
    wins_1000 = np.sum(roes >= 1000) # 11배+
    losses = np.sum(roes < 0)
    avg_win = np.mean([r for r in roes if r > 0]) if any(r > 0 for r in roes) else 0
    avg_loss = np.mean([r for r in roes if r < 0]) if any(r < 0 for r in roes) else 0
    max_win_roe = roes.max()
    max_win_pnl = pnls.max()
    p95_roe = np.percentile(roes, 95)
    return {
        "n": len(trades),
        "n_wins_100pct": int(wins_100),
        "n_wins_200pct": int(wins_200),
        "n_wins_500pct": int(wins_500),
        "n_wins_1000pct": int(wins_1000),
        "n_losses": int(losses),
        "p_double_or_more": float(wins_100 / len(trades)),
        "p_triple_or_more": float(wins_200 / len(trades)),
        "avg_win_roe": round(float(avg_win), 1),
        "avg_loss_roe": round(float(avg_loss), 1),
        "max_win_roe": round(float(max_win_roe), 1),
        "max_win_pnl": round(float(max_win_pnl), 2),
        "p95_roe": round(float(p95_roe), 1),
        "first_trade_roe": round(float(roes[0]), 1),
        "first_trade_pnl": round(float(pnls[0]), 2),
        "first_3_pnl": round(float(pnls[:3].sum()), 2),
        "first_5_pnl": round(float(pnls[:5].sum()), 2),
        "ev_per_trade_pnl": round(float(pnls.mean()), 2),
        "best_3_pnl": round(float(np.sort(pnls)[-3:].sum()), 2),
        "best_1_pnl": round(float(pnls.max()), 2),
    }


def main():
    t0 = time.time()
    # Load all relevant symbols
    syms = ["PEPEUSDT", "DOGEUSDT", "WIFUSDT", "ETHUSDT", "SOLUSDT", "BTCUSDT", "OPUSDT", "SUIUSDT"]
    cache = {s: compute_indicators(load_1h(s)) for s in syms if load_1h(s) is not None}
    print(f"[load] {len(cache)} syms, {min(len(v['close']) for v in cache.values())} bars")

    # Each config: signal × universe × (TP, SL) at lev=30, mp=1.0 (full margin)
    configs = []
    universes = ["PEPE_only", "PEPE_DOGE", "memes_first", "memes_alts", "rotation_30x_orig"]
    signals = ["x1", "atr_breakout", "momentum", "combined"]
    # 한탕 settings: high TP, accept big SL since 30x means SL will be tight in price terms
    # At 30x: SL=-50% ROE = -1.67% price; SL=-30% ROE = -1% price; SL=-100% = wipeout
    setup_grid = [
        # name, tp_roe, sl_roe, hold_h
        ("Q1_quick_double",  100, -50, 24),    # +3.33% px → double; -1.67% px → -$25 loss
        ("Q2_aggressive_3x", 200, -50, 48),    # +6.67% px → triple; -1.67% px → -$25
        ("Q3_homerun_6x",    500, -50, 72),    # +16.67% px → 6x; -1.67% px → -$25
        ("Q4_lottery_10x",   1000, -50, 96),   # +33% px → 11x; rare but possible
        ("Q5_double_tight",  100, -30, 24),    # tight SL, double target
        ("Q6_triple_tight",  200, -30, 48),    # tight SL, triple target
        ("Q7_homerun_tight", 500, -30, 72),    # tight SL, homerun
        ("Q8_safer_double",  100, -70, 24),    # wider SL, double target (more breath)
    ]

    rows = []
    for univ in universes:
        priority = PRIORITY_UNIVERSES[univ]
        if not all(s in cache for s in priority): continue
        for sig in signals:
            for setup_name, tp, sl, h in setup_grid:
                # Use full margin for "한탕" (mp=1.0)
                long_only = (sig == "turnaround")
                r = big_hit_analysis(priority, cache, sig, 30, 1.0, tp, sl, h, long_only)
                if r is None: continue
                rows.append({
                    "univ": univ, "sig": sig, "setup": setup_name,
                    "tp_roe": tp, "sl_roe": sl, "hold_h": h, **r,
                })

    print(f"\n[done] {len(rows)} configs analyzed in {time.time()-t0:.1f}s")

    # ===== Ranking =====
    print(f"\n{'='*140}\n=== TOP-15 by BEST_3_PNL (3개 트레이드 합산 최대) ===\n{'='*140}")
    rows.sort(key=lambda r: -r["best_3_pnl"])
    print(f"{'rank':>4s} {'univ':<18s} {'sig':<13s} {'setup':<22s} {'tp':>4s} {'sl':>4s} {'N':>3s} {'p_dbl':>6s} {'p_3x':>6s} {'avgW%':>6s} {'maxW%':>7s} {'maxW$':>8s} {'best1$':>7s} {'best3$':>7s} {'first1$':>8s} {'first5$':>8s} {'EV$':>7s}")
    for i, r in enumerate(rows[:15], 1):
        print(f"  {i:>2d} {r['univ']:<18s} {r['sig']:<13s} {r['setup']:<22s} {r['tp_roe']:>4d} {r['sl_roe']:>4d} {r['n']:>3d} {r['p_double_or_more']*100:>5.1f}% {r['p_triple_or_more']*100:>5.1f}% {r['avg_win_roe']:>5.0f} {r['max_win_roe']:>6.0f} ${r['max_win_pnl']:>+6.1f} ${r['best_1_pnl']:>+5.1f} ${r['best_3_pnl']:>+5.1f} ${r['first_trade_pnl']:>+6.1f} ${r['first_5_pnl']:>+6.1f} ${r['ev_per_trade_pnl']:>+5.1f}")

    print(f"\n{'='*140}\n=== TOP-15 by FIRST_TRADE_PNL (첫 트레이드 기대값) ===\n{'='*140}")
    rows_f = sorted(rows, key=lambda r: -r["first_trade_pnl"])
    print(f"{'rank':>4s} {'univ':<18s} {'sig':<13s} {'setup':<22s} {'tp':>4s} {'sl':>4s} {'first1$':>8s} {'first3$':>8s} {'first5$':>8s} {'EV$':>7s} {'p_dbl':>6s}")
    for i, r in enumerate(rows_f[:15], 1):
        print(f"  {i:>2d} {r['univ']:<18s} {r['sig']:<13s} {r['setup']:<22s} {r['tp_roe']:>4d} {r['sl_roe']:>4d} ${r['first_trade_pnl']:>+6.1f} ${r['first_3_pnl']:>+6.1f} ${r['first_5_pnl']:>+6.1f} ${r['ev_per_trade_pnl']:>+5.1f} {r['p_double_or_more']*100:>5.1f}%")

    print(f"\n{'='*140}\n=== TOP-15 by P_TRIPLE_OR_MORE (3배 이상 hit 확률) ===\n{'='*140}")
    rows_t = sorted([r for r in rows if r['n'] >= 5], key=lambda r: -r["p_triple_or_more"])
    print(f"{'rank':>4s} {'univ':<18s} {'sig':<13s} {'setup':<22s} {'tp':>4s} {'sl':>4s} {'N':>3s} {'p_dbl':>6s} {'p_3x':>6s} {'p_6x':>6s} {'maxW%':>7s} {'best1$':>8s}")
    for i, r in enumerate(rows_t[:15], 1):
        p_6x = r['n_wins_500pct'] / r['n']
        print(f"  {i:>2d} {r['univ']:<18s} {r['sig']:<13s} {r['setup']:<22s} {r['tp_roe']:>4d} {r['sl_roe']:>4d} {r['n']:>3d} {r['p_double_or_more']*100:>5.1f}% {r['p_triple_or_more']*100:>5.1f}% {p_6x*100:>5.1f}% {r['max_win_roe']:>6.0f} ${r['best_1_pnl']:>+6.1f}")

    OUT.write_text(json.dumps(rows, indent=2, default=str))
    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()
