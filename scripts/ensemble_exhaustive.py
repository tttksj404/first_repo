"""Exhaustive factorial ensemble backtest + 3-Model Debate consensus.

Phase 1: Brute-force ALL 31 factor combos (2^5-1) × leverage × weights × margin
Phase 2: 3 independent "model" perspectives each rank the results
  Model 1 (Risk-Guard):      min ruin, min DD, then EV
  Model 2 (Alpha-Hunter):    max EV, max PF, max PnL
  Model 3 (Robustness-Judge): WF=4/4, sufficient trades, stable EV
Phase 3: Consensus = intersection of all 3 models' top picks

Factors:
  A: Vol-managed momentum
  B: Cross-sectional winner rotation
  C: Short-term reversal (buy crash dips)
  D: Regime detection (BTC-based gate)
  E: BTC-residual strength
"""
import json, random, statistics, time, math
from pathlib import Path

dd = Path("quant_runtime/historical")
COST_RT = 0.0012
EQUITY  = 75.0
MC_SIMS = 2000
HOLD_BARS = 168     # 7d
SL_ROE  = -15       # stop-loss ROE %
COOLDOWN = 48       # 2d cooldown

WEIGHT_PROFILES = {
    "equal":     {"A": 1.0, "B": 1.0, "C": 1.0, "E": 1.0},
    "mom_heavy": {"A": 2.0, "B": 1.5, "C": 0.5, "E": 1.0},
    "rev_heavy": {"A": 0.5, "B": 0.5, "C": 2.5, "E": 0.5},
    "alpha_mix": {"A": 1.5, "B": 0.8, "C": 2.0, "E": 1.2},
}

LEVERAGES = [5, 10, 15, 20]
MARGIN_PCTS = [0.50, 0.75]

# ── Load data ──
all_coins = {}
for sym_dir in sorted(dd.iterdir()):
    if not sym_dir.is_dir(): continue
    sym = sym_dir.name; p1h = sym_dir / "1h.json"
    if not p1h.exists(): continue
    b1 = json.load(open(p1h))
    if len(b1) < 5000: continue
    all_coins[sym] = [b["close_price"] for b in b1]

btc = all_coins.get("BTCUSDT", [])
n = min(len(c) for c in all_coins.values())
syms = sorted(all_coins.keys())
print(f"Loaded {len(syms)} coins, {n} bars ({n/24:.0f}d)\n", flush=True)


# ═══════════════════════════════════════════
#  Factor functions
# ═══════════════════════════════════════════

def factor_a_signal(c, i, lookback=168):
    if i < lookback + 50: return 0
    mom = (c[i] - c[i-lookback]) / c[i-lookback]
    rets = [(c[i-j] - c[i-j-1]) / c[i-j-1] for j in range(1, min(240, i))]
    vol = statistics.stdev(rets) if len(rets) > 10 else 1
    if vol < 0.0001: return 0
    return mom / vol

def factor_b_ranks(all_c, i, lookback=168):
    moms = {}
    for sym, c in all_c.items():
        if i >= len(c) or i < lookback: continue
        moms[sym] = (c[i] - c[i-lookback]) / c[i-lookback]
    ranked = sorted(moms.items(), key=lambda x: -x[1])
    return {sym: rank for rank, (sym, _) in enumerate(ranked)}

def factor_c_signal(c, i, lookback=72):
    if i < lookback: return 0
    ret_3d = (c[i] - c[i-lookback]) / c[i-lookback]
    return 1 if ret_3d < -0.10 else 0

def detect_regime(btc_c, i):
    if i < 720: return 1
    ret_5d = (btc_c[i] - btc_c[i-120]) / btc_c[i-120]
    e20 = sum(btc_c[max(0,i-20):i+1]) / min(20, i+1)
    e50 = sum(btc_c[max(0,i-50):i+1]) / min(50, i+1)
    if ret_5d < -0.08: return 0
    if e20 > e50: return 2
    return 1

def factor_e_signal(c, btc_c, i, lookback=168):
    if i < lookback or i >= len(btc_c): return 0
    coin_ret = (c[i] - c[i-lookback]) / c[i-lookback]
    btc_ret = (btc_c[i] - btc_c[i-lookback]) / btc_c[i-lookback]
    return coin_ret - btc_ret


# ═══════════════════════════════════════════
#  Core backtest engine
# ═══════════════════════════════════════════

def run_backtest(use_A, use_B, use_C, use_D, use_E, weights, lev, mp):
    margin = EQUITY * mp; notional = margin * lev; fee = notional * COST_RT
    trades = []; pos = None; cd = 0; sym_hist = {}

    for i in range(720, n, 24):
        if pos:
            c = all_coins[pos["sym"]]
            if i >= len(c): pos = None; continue
            roe = (c[i]/pos["bp"]-1)*100*lev
            hh = i - pos["ei"]; fd = notional*0.0001*(hh//8)
            if roe <= SL_ROE:
                trades.append(margin*(SL_ROE/100)-fee-fd); pos=None; cd=i+COOLDOWN; continue
            if hh >= HOLD_BARS:
                trades.append(margin*(roe/100)-fee-fd); pos=None; continue
            continue
        if i < cd: continue

        regime = detect_regime(btc, i) if use_D else 2
        if regime == 0: continue

        scores = {}
        ranks = factor_b_ranks(all_coins, i) if use_B else {}

        for sym, c in all_coins.items():
            if sym == "BTCUSDT" or i >= len(c): continue
            score = 0
            if use_A:
                w_a = weights["A"] * (1.5 if (use_D and regime==2) else 1.0)
                score += factor_a_signal(c, i) * w_a
            if use_B and sym in ranks:
                w_b = weights["B"] * (1.3 if (use_D and regime==1) else 1.0)
                score += (1.0 - ranks[sym]/max(len(ranks),1)) * w_b
            if use_C:
                w_c = weights["C"] * (1.5 if (use_D and regime==1) else 1.0)
                score += factor_c_signal(c, i) * w_c
            if use_E:
                score += factor_e_signal(c, btc, i) * weights["E"]
            scores[sym] = score

        if not scores: continue
        best = max(scores.items(), key=lambda x: x[1])
        if best[1] <= 0: continue
        pos = {"sym": best[0], "bp": all_coins[best[0]][i], "ei": i}
        sym_hist[best[0]] = sym_hist.get(best[0], 0) + 1

    return trades, sym_hist


def calc_metrics(trades, lev, mp):
    if not trades or len(trades) < 8: return None
    nt = len(trades); w = sum(1 for t in trades if t>0); total = sum(trades)
    if total <= 0: return None

    gp = sum(t for t in trades if t>0); gl = abs(sum(t for t in trades if t<=0))
    pf = gp/max(gl,0.01); wr = w/max(nt,1); aw = gp/max(w,1); al = gl/max(nt-w,1)
    ev = wr*aw - (1-wr)*al; tpm = nt/(n/24)*30

    # Walk-forward 4 folds
    fs = max(nt//4, 1)
    wf = sum(1 for fi in range(4) if sum(trades[fi*fs:(fi+1)*fs if fi<3 else nt])>0)

    # MC ruin
    ruin = 0
    for _ in range(MC_SIMS):
        bal = EQUITY
        for t in random.choices(trades, k=nt):
            bal += t
            if bal <= 0: ruin += 1; break

    # Max drawdown
    peak = EQUITY; max_dd = 0; bal = EQUITY
    for t in trades:
        bal += t
        if bal > peak: peak = bal
        dd = (peak-bal)/peak
        if dd > max_dd: max_dd = dd

    # Sharpe-like: mean(trade) / stdev(trade)
    m = total / nt
    sd = statistics.stdev(trades) if nt > 2 else 1
    sharpe = m / sd if sd > 0 else 0

    # Calmar-like: total return / max dd
    calmar = (total / EQUITY) / max_dd if max_dd > 0 else 0

    return {
        "trades": nt, "tpm": round(tpm,1), "wr": round(wr*100,1),
        "aw": round(aw,2), "al": round(al,2), "ev": round(ev,2),
        "pf": round(pf,2), "wf": wf, "ruin_pct": round(ruin/MC_SIMS*100,1),
        "max_dd_pct": round(max_dd*100,1), "total_pnl": round(total,2),
        "sharpe": round(sharpe,3), "calmar": round(calmar,2),
    }


# ═══════════════════════════════════════════
#  PHASE 1: Exhaustive sweep
# ═══════════════════════════════════════════

factor_combos = []
for bits in range(1, 32):
    A = bool(bits & 1); B = bool(bits & 2); C = bool(bits & 4)
    D = bool(bits & 8); E = bool(bits & 16)
    label = ("A" if A else "") + ("B" if B else "") + ("C" if C else "") + ("D" if D else "") + ("E" if E else "")
    factor_combos.append((label, A, B, C, D, E))

total_configs = len(factor_combos) * len(WEIGHT_PROFILES) * len(LEVERAGES) * len(MARGIN_PCTS)
print(f"{'='*80}")
print(f"PHASE 1: EXHAUSTIVE SWEEP")
print(f"  Factor combos: {len(factor_combos)} (2^5-1)")
print(f"  Weight profiles: {len(WEIGHT_PROFILES)} ({', '.join(WEIGHT_PROFILES)})")
print(f"  Leverage: {LEVERAGES}")
print(f"  Margin: {MARGIN_PCTS}")
print(f"  TOTAL: {total_configs} configs")
print(f"{'='*80}", flush=True)

results = []
t0 = time.time(); done = 0

for (label, A, B, C, D, E) in factor_combos:
    for wp_name, weights in WEIGHT_PROFILES.items():
        for lev in LEVERAGES:
            for mp in MARGIN_PCTS:
                trades, sym_hist = run_backtest(A, B, C, D, E, weights, lev, mp)
                m = calc_metrics(trades, lev, mp) if trades else None
                done += 1
                if m:
                    m["factors"] = label; m["weights"] = wp_name
                    m["lev"] = lev; m["margin_pct"] = mp
                    m["coin_count"] = len(sym_hist)
                    m["top_coins"] = sorted(sym_hist.items(), key=lambda x:-x[1])[:5]
                    results.append(m)
                if done % 100 == 0:
                    el = time.time()-t0; rate = done/el if el>0 else 1
                    eta = (total_configs-done)/rate
                    print(f"  [{done}/{total_configs}] {el:.0f}s, ~{eta:.0f}s left, {len(results)} viable", flush=True)

elapsed = time.time()-t0
print(f"\nSweep done: {total_configs} configs in {elapsed:.1f}s → {len(results)} viable\n", flush=True)


# ═══════════════════════════════════════════
#  PHASE 2: 3-MODEL DEBATE
# ═══════════════════════════════════════════

print(f"{'='*80}")
print(f"PHASE 2: 3-MODEL DEBATE")
print(f"{'='*80}\n", flush=True)

TOP_K = 20  # each model picks top-20


def model_1_risk_guard(results):
    """Risk-Guard: minimize ruin → minimize DD → then maximize EV.
    Hard filter: ruin < 10%, DD < 60%. Score = -ruin*5 - dd*2 + ev."""
    pool = [r for r in results if r["ruin_pct"] < 10 and r["max_dd_pct"] < 60]
    for r in pool:
        r["_m1_score"] = -r["ruin_pct"]*5 - r["max_dd_pct"]*2 + r["ev"]*3
    pool.sort(key=lambda x: -x["_m1_score"])
    return pool[:TOP_K]


def model_2_alpha_hunter(results):
    """Alpha-Hunter: maximize risk-adjusted returns.
    Score = EV*4 + PF*5 + sharpe*10 + calmar*3. Min filter: EV > 0."""
    pool = [r for r in results if r["ev"] > 0]
    for r in pool:
        r["_m2_score"] = r["ev"]*4 + r["pf"]*5 + r["sharpe"]*10 + r["calmar"]*3
    pool.sort(key=lambda x: -x["_m2_score"])
    return pool[:TOP_K]


def model_3_robustness_judge(results):
    """Robustness-Judge: walk-forward consistency + sufficient trades + stability.
    Hard filter: WF >= 3, trades >= 15. Score = WF*20 + trades*0.3 + pf*3 + ev*2 - ruin."""
    pool = [r for r in results if r["wf"] >= 3 and r["trades"] >= 15]
    for r in pool:
        r["_m3_score"] = r["wf"]*20 + r["trades"]*0.3 + r["pf"]*3 + r["ev"]*2 - r["ruin_pct"]
    pool.sort(key=lambda x: -x["_m3_score"])
    return pool[:TOP_K]


def config_key(r):
    return f"{r['factors']}|{r['weights']}|{r['lev']}x|{r['margin_pct']}"


m1_picks = model_1_risk_guard(results)
m2_picks = model_2_alpha_hunter(results)
m3_picks = model_3_robustness_judge(results)


def print_picks(label, picks, score_key):
    print(f"\n── {label} TOP {len(picks)} ──")
    print(f"{'#':>3} {'Score':>7} {'Factors':>8} {'Wts':>10} {'Lev':>4} {'MP':>4} | {'#T':>4} {'WR%':>5} {'EV$':>7} {'PF':>5} {'WF':>3} {'Ruin%':>6} {'DD%':>5} {'Shrp':>5} | {'PnL$':>8}")
    print("-" * 105)
    for i, r in enumerate(picks):
        sc = r.get(score_key, 0)
        print(f"{i+1:>3} {sc:>7.1f} {r['factors']:>8} {r['weights']:>10} {r['lev']:>4}x {r['margin_pct']*100:>3.0f}% | "
              f"{r['trades']:>4} {r['wr']:>5.1f} {r['ev']:>7.2f} {r['pf']:>5.2f} {r['wf']:>3}/4 {r['ruin_pct']:>5.1f}% {r['max_dd_pct']:>5.1f} {r['sharpe']:>5.3f} | ${r['total_pnl']:>+8.0f}")


print_picks("MODEL 1 — Risk-Guard", m1_picks, "_m1_score")
print_picks("MODEL 2 — Alpha-Hunter", m2_picks, "_m2_score")
print_picks("MODEL 3 — Robustness-Judge", m3_picks, "_m3_score")


# ═══════════════════════════════════════════
#  PHASE 3: CONSENSUS (intersection)
# ═══════════════════════════════════════════

print(f"\n\n{'='*80}")
print(f"PHASE 3: 3-MODEL CONSENSUS")
print(f"{'='*80}\n", flush=True)

m1_keys = {config_key(r) for r in m1_picks}
m2_keys = {config_key(r) for r in m2_picks}
m3_keys = {config_key(r) for r in m3_picks}

# Strict consensus: all 3 agree
consensus_3 = m1_keys & m2_keys & m3_keys
# Relaxed: any 2 of 3 agree
consensus_2of3 = (m1_keys & m2_keys) | (m1_keys & m3_keys) | (m2_keys & m3_keys)

key_to_result = {config_key(r): r for r in results}

print(f"3/3 consensus: {len(consensus_3)} configs")
print(f"2/3 consensus: {len(consensus_2of3)} configs\n")


def print_consensus(label, keys, model_keys_list):
    clist = []
    for k in keys:
        r = key_to_result[k]
        votes = sum(1 for mk in model_keys_list if k in mk)
        # Composite score: average of normalized model scores
        r["_votes"] = votes
        r["_composite"] = r["ev"]*3 + r["pf"]*4 - r["ruin_pct"]*2 + r["wf"]*10 + r["sharpe"]*8
        clist.append(r)
    clist.sort(key=lambda x: (-x["_votes"], -x["_composite"]))

    print(f"── {label} ──")
    if not clist:
        print("  (none)")
        return clist
    print(f"{'#':>3} {'V':>2} {'Comp':>7} {'Factors':>8} {'Wts':>10} {'Lev':>4} {'MP':>4} | {'#T':>4} {'WR%':>5} {'EV$':>7} {'PF':>5} {'WF':>3} {'Ruin%':>6} {'DD%':>5} {'Shrp':>5} | {'PnL$':>8}")
    print("-" * 110)
    for i, r in enumerate(clist):
        print(f"{i+1:>3} {r['_votes']:>2} {r['_composite']:>7.1f} {r['factors']:>8} {r['weights']:>10} {r['lev']:>4}x {r['margin_pct']*100:>3.0f}% | "
              f"{r['trades']:>4} {r['wr']:>5.1f} {r['ev']:>7.2f} {r['pf']:>5.2f} {r['wf']:>3}/4 {r['ruin_pct']:>5.1f}% {r['max_dd_pct']:>5.1f} {r['sharpe']:>5.3f} | ${r['total_pnl']:>+8.0f}")
    return clist


c3_list = print_consensus("FULL CONSENSUS (3/3)", consensus_3, [m1_keys, m2_keys, m3_keys])
print()
c2_list = print_consensus("MAJORITY CONSENSUS (2/3)", consensus_2of3, [m1_keys, m2_keys, m3_keys])


# ═══════════════════════════════════════════
#  FINAL VERDICT
# ═══════════════════════════════════════════

print(f"\n\n{'='*80}")
print("FINAL VERDICT: 3-MODEL DEBATE RESULT")
print(f"{'='*80}\n")

verdict_pool = c3_list if c3_list else c2_list
if verdict_pool:
    winner = verdict_pool[0]
    print(f"  WINNER: {winner['factors']} | weights={winner['weights']} | {winner['lev']}x | margin={winner['margin_pct']*100:.0f}%")
    print(f"  Trades: {winner['trades']} ({winner['tpm']:.1f}/mo)")
    print(f"  WR: {winner['wr']:.1f}% | AvgWin: ${winner['aw']:.2f} | AvgLoss: ${winner['al']:.2f}")
    print(f"  EV: ${winner['ev']:.2f} | PF: {winner['pf']:.2f} | Sharpe: {winner['sharpe']:.3f}")
    print(f"  WF: {winner['wf']}/4 | Ruin: {winner['ruin_pct']:.1f}% | MaxDD: {winner['max_dd_pct']:.1f}%")
    print(f"  Total PnL: ${winner['total_pnl']:+.2f}")
    if winner.get("top_coins"):
        coins_str = ", ".join(f"{s}({n})" for s,n in winner["top_coins"])
        print(f"  Top coins: {coins_str}")
    print(f"  Votes: {winner.get('_votes', '?')}/3 models agree")

    # Compare to individual factor C baseline
    c_only = [r for r in results if r["factors"] == "C"]
    if c_only:
        best_c = max(c_only, key=lambda x: x["ev"])
        print(f"\n  Baseline (C only): EV=${best_c['ev']:.2f} PF={best_c['pf']:.2f} Ruin={best_c['ruin_pct']:.1f}%")
        ev_delta = winner["ev"] - best_c["ev"]
        print(f"  Ensemble edge: EV ${ev_delta:+.2f} vs individual C")
        if ev_delta > 0:
            print(f"  → ENSEMBLE WINS by ${ev_delta:.2f}/trade")
        else:
            print(f"  → Individual C still superior; ensemble adds diversification but costs EV")
else:
    print("  NO CONSENSUS FOUND — models disagree completely.")
    print("  Falling back to best per individual model:")
    if m1_picks:
        r = m1_picks[0]
        print(f"  M1(Risk):   {r['factors']}|{r['weights']}|{r['lev']}x EV=${r['ev']:.2f} ruin={r['ruin_pct']:.1f}%")
    if m2_picks:
        r = m2_picks[0]
        print(f"  M2(Alpha):  {r['factors']}|{r['weights']}|{r['lev']}x EV=${r['ev']:.2f} PF={r['pf']:.2f}")
    if m3_picks:
        r = m3_picks[0]
        print(f"  M3(Robust): {r['factors']}|{r['weights']}|{r['lev']}x EV=${r['ev']:.2f} WF={r['wf']}/4")

# ── Individual factor benchmark ──
print(f"\n{'='*80}")
print("INDIVIDUAL FACTOR BENCHMARKS")
print(f"{'='*80}")
best_per_single = {}
for r in results:
    if len(r["factors"]) == 1:
        f = r["factors"]
        if f not in best_per_single or r["ev"] > best_per_single[f]["ev"]:
            best_per_single[f] = r
for f in "ABCDE":
    if f in best_per_single:
        r = best_per_single[f]
        print(f"  {f}: EV=${r['ev']:.2f} PF={r['pf']:.2f} WR={r['wr']:.1f}% ruin={r['ruin_pct']:.1f}% WF={r['wf']}/4 {r['lev']}x {r['weights']} PnL=${r['total_pnl']:+.0f}")
    else:
        print(f"  {f}: (no viable config)")

# ── Save ──
out = {"metadata": {"total_configs": total_configs, "viable": len(results),
       "elapsed_s": round(elapsed,1), "coins": len(syms), "bars": n,
       "mc_sims": MC_SIMS, "hold_bars": HOLD_BARS, "sl_roe": SL_ROE},
       "all_results": results[:500],
       "model1_picks": [config_key(r) for r in m1_picks],
       "model2_picks": [config_key(r) for r in m2_picks],
       "model3_picks": [config_key(r) for r in m3_picks],
       "consensus_3of3": list(consensus_3),
       "consensus_2of3": list(consensus_2of3),
       "verdict": config_key(verdict_pool[0]) if verdict_pool else None}

out_path = Path("quant_runtime/output/ensemble_exhaustive.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
json.dump(out, open(out_path, "w"), indent=1)
print(f"\nSaved → {out_path}")
print("Done.", flush=True)
