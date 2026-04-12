"""Full factorial ensemble backtest — ALL variables.

Phase 1: 31 factors × 4 lev × 4 margin × 4 SL = 1,984 configs (default hold=168, weights=equal, cd=48)
Phase 2: Top 50 from Phase 1 × 3 hold × 4 weights × 3 cooldown = 1,800 configs

Variables:
  Factors: A(VolMom) B(XSect) C(Reversal) D(Regime) E(BTCResid) — 31 combos
  Leverage: 5, 10, 15, 20
  Margin: 25%, 50%, 75%, 100%
  SL ROE: 10%, 15%, 20%, 30%
  Hold: 3d(72h), 7d(168h), 14d(336h)
  Weights: equal, mom_heavy, rev_heavy, alpha_mix
  Cooldown: 24h, 48h, 72h
"""
import json, random, statistics, time
from pathlib import Path

dd = Path("quant_runtime/historical")
COST_RT = 0.0012
EQUITY = 75.0
MC_SIMS = 1000

WEIGHT_PROFILES = {
    "equal": {"A": 1.0, "B": 1.0, "C": 1.0, "E": 1.0},
    "mom_heavy": {"A": 2.0, "B": 1.5, "C": 0.5, "E": 1.0},
    "rev_heavy": {"A": 0.5, "B": 0.5, "C": 2.5, "E": 0.5},
    "alpha_mix": {"A": 1.5, "B": 0.8, "C": 2.0, "E": 1.2},
}

# Load data
all_coins = {}
for sym_dir in sorted(dd.iterdir()):
    if not sym_dir.is_dir(): continue
    p1h = sym_dir / "1h.json"
    if not p1h.exists(): continue
    b1 = json.load(open(p1h))
    if len(b1) < 5000: continue
    all_coins[sym_dir.name] = [b["close_price"] for b in b1]

btc = all_coins.get("BTCUSDT", [])
n = min(len(c) for c in all_coins.values())
print(f"Loaded {len(all_coins)} coins, {n} bars ({n//24}d)\n", flush=True)

# Factor functions
def factor_a(c, i):
    if i < 218: return 0
    mom = (c[i]-c[i-168])/c[i-168]
    rets = [(c[i-j]-c[i-j-1])/c[i-j-1] for j in range(1, min(240,i))]
    vol = statistics.stdev(rets) if len(rets)>10 else 1
    return mom/vol if vol > 0.0001 else 0

def factor_b_ranks(all_c, i):
    moms = {s:(c[i]-c[i-168])/c[i-168] for s,c in all_c.items() if i<len(c) and i>=168}
    ranked = sorted(moms.items(), key=lambda x:-x[1])
    return {s:r for r,(s,_) in enumerate(ranked)}

def factor_c(c, i):
    if i < 72: return 0
    return 1 if (c[i]-c[i-72])/c[i-72] < -0.10 else 0

def detect_regime(btc_c, i):
    if i < 720: return 1
    ret = (btc_c[i]-btc_c[i-120])/btc_c[i-120]
    if ret < -0.08: return 0
    e20 = sum(btc_c[max(0,i-20):i+1])/min(20,i+1)
    e50 = sum(btc_c[max(0,i-50):i+1])/min(50,i+1)
    return 2 if e20>e50 else 1

def factor_e(c, btc_c, i):
    if i < 168 or i >= len(btc_c): return 0
    return (c[i]-c[i-168])/c[i-168] - (btc_c[i]-btc_c[i-168])/btc_c[i-168]

def run_bt(use_A, use_B, use_C, use_D, use_E, weights, lev, mp, sl_roe, hold_bars, cooldown):
    margin = EQUITY*mp; notional = margin*lev; fee = notional*COST_RT
    trades = []; pos = None; cd = 0; sym_hist = {}
    for i in range(720, n, 24):
        if pos:
            c = all_coins[pos["sym"]]
            if i >= len(c): pos=None; continue
            roe = (c[i]/pos["bp"]-1)*100*lev
            hh = i-pos["ei"]; fd = notional*0.0001*(hh//8)
            if roe <= -sl_roe:
                trades.append(margin*(-sl_roe/100)-fee-fd); pos=None; cd=i+cooldown; continue
            if hh >= hold_bars:
                trades.append(margin*(roe/100)-fee-fd); pos=None; continue
            continue
        if i < cd: continue
        regime = detect_regime(btc, i) if use_D else 2
        if regime == 0: continue
        scores = {}; ranks = factor_b_ranks(all_coins, i) if use_B else {}
        for sym, c in all_coins.items():
            if sym=="BTCUSDT" or i>=len(c): continue
            score = 0
            if use_A: score += factor_a(c,i) * weights["A"] * (1.5 if (use_D and regime==2) else 1.0)
            if use_B and sym in ranks: score += (1.0-ranks[sym]/max(len(ranks),1)) * weights["B"] * (1.3 if (use_D and regime==1) else 1.0)
            if use_C: score += factor_c(c,i) * weights["C"] * (1.5 if (use_D and regime==1) else 1.0)
            if use_E: score += factor_e(c,btc,i) * weights["E"]
            scores[sym] = score
        if not scores: continue
        best = max(scores.items(), key=lambda x:x[1])
        if best[1] <= 0: continue
        pos = {"sym":best[0],"bp":all_coins[best[0]][i],"ei":i}
        sym_hist[best[0]] = sym_hist.get(best[0],0)+1
    return trades, sym_hist

def calc_metrics(trades):
    if not trades or len(trades)<8: return None
    nt=len(trades); w=sum(1 for t in trades if t>0); total=sum(trades)
    if total<=0: return None
    gp=sum(t for t in trades if t>0); gl=abs(sum(t for t in trades if t<=0))
    pf=gp/max(gl,0.01); wr=w/max(nt,1); aw=gp/max(w,1); al=gl/max(nt-w,1)
    ev=wr*aw-(1-wr)*al; tpm=nt/(n/24)*30
    fs=max(nt//4,1)
    wf=sum(1 for fi in range(4) if sum(trades[fi*fs:(fi+1)*fs if fi<3 else nt])>0)
    ruin=0
    for _ in range(MC_SIMS):
        bal=EQUITY
        for t in random.choices(trades,k=nt):
            bal+=t
            if bal<=0: ruin+=1; break
    peak=EQUITY; max_dd=0; bal=EQUITY
    for t in trades:
        bal+=t
        if bal>peak: peak=bal
        dd=(peak-bal)/peak
        if dd>max_dd: max_dd=dd
    m=total/nt; sd=statistics.stdev(trades) if nt>2 else 1
    sharpe=m/sd if sd>0 else 0
    return {"trades":nt,"tpm":round(tpm,1),"wr":round(wr*100,1),"aw":round(aw,2),"al":round(al,2),
            "ev":round(ev,2),"pf":round(pf,2),"wf":wf,"ruin_pct":round(ruin/MC_SIMS*100,1),
            "max_dd_pct":round(max_dd*100,1),"total_pnl":round(total,2),"sharpe":round(sharpe,3)}

# ═══════════════ PHASE 1 ═══════════════
print("="*80)
print("PHASE 1: 31 factors × 4 lev × 4 margin × 4 SL = 1,984 configs")
print("="*80, flush=True)

factor_combos = []
for bits in range(1, 32):
    A=bool(bits&1); B=bool(bits&2); C=bool(bits&4); D=bool(bits&8); E=bool(bits&16)
    label=("A" if A else "")+("B" if B else "")+("C" if C else "")+("D" if D else "")+("E" if E else "")
    factor_combos.append((label,A,B,C,D,E))

LEVERAGES = [5, 10, 15, 20]
MARGINS = [0.25, 0.50, 0.75, 1.0]
SL_ROES = [10, 15, 20, 30]
DEFAULT_HOLD = 168
DEFAULT_WEIGHTS = WEIGHT_PROFILES["equal"]
DEFAULT_CD = 48

results_p1 = []
t0 = time.time(); done = 0
total_p1 = len(factor_combos)*len(LEVERAGES)*len(MARGINS)*len(SL_ROES)

for (label,A,B,C,D,E) in factor_combos:
    for lev in LEVERAGES:
        for mp in MARGINS:
            for sl in SL_ROES:
                trades, sh = run_bt(A,B,C,D,E,DEFAULT_WEIGHTS,lev,mp,sl,DEFAULT_HOLD,DEFAULT_CD)
                m = calc_metrics(trades) if trades else None
                done += 1
                if m:
                    m.update({"factors":label,"lev":lev,"margin":mp,"sl_roe":sl,
                              "hold":DEFAULT_HOLD,"weights":"equal","cooldown":DEFAULT_CD,
                              "coin_count":len(sh)})
                    results_p1.append(m)
                if done % 200 == 0:
                    el=time.time()-t0; rate=done/el if el>0 else 1
                    print(f"  [{done}/{total_p1}] {el:.0f}s, ~{(total_p1-done)/rate:.0f}s left, {len(results_p1)} viable", flush=True)

results_p1.sort(key=lambda x:-x["ev"])
print(f"\nPhase 1 done: {len(results_p1)} viable / {total_p1} tested in {time.time()-t0:.0f}s")
print(f"\nTOP 20 Phase 1:")
print(f"{'#':>3} {'Factors':>8} {'Lev':>4} {'MP':>4} {'SL':>3} | {'#T':>4} {'WR%':>5} {'EV$':>7} {'PF':>5} {'WF':>3} {'Ruin%':>6} | {'PnL$':>8}")
print("-"*85)
for i,r in enumerate(results_p1[:20]):
    print(f"{i+1:>3} {r['factors']:>8} {r['lev']:>4}x {r['margin']*100:>3.0f}% {r['sl_roe']:>3}% | "
          f"{r['trades']:>4} {r['wr']:>5.1f} {r['ev']:>7.2f} {r['pf']:>5.2f} {r['wf']:>3}/4 {r['ruin_pct']:>5.1f}% | ${r['total_pnl']:>+8.0f}")

# ═══════════════ PHASE 2 ═══════════════
print(f"\n{'='*80}")
print("PHASE 2: Top 50 × 3 hold × 4 weights × 3 cooldown = 1,800 configs")
print("="*80, flush=True)

HOLDS = [72, 168, 336]
COOLDOWNS = [24, 48, 72]
top50 = results_p1[:50]

results_p2 = []
t1 = time.time(); done2 = 0
total_p2 = len(top50)*len(HOLDS)*len(WEIGHT_PROFILES)*len(COOLDOWNS)

for base in top50:
    label = base["factors"]
    bits = sum(1<<i for i,f in enumerate("ABCDE") if f in label)
    A=bool(bits&1); B=bool(bits&2); C=bool(bits&4); D=bool(bits&8); E=bool(bits&16)
    lev = base["lev"]; mp = base["margin"]; sl = base["sl_roe"]

    for hold in HOLDS:
        for wp_name, weights in WEIGHT_PROFILES.items():
            for cd in COOLDOWNS:
                # Skip the default combo (already tested in P1)
                if hold==DEFAULT_HOLD and wp_name=="equal" and cd==DEFAULT_CD:
                    done2+=1; continue
                trades, sh = run_bt(A,B,C,D,E,weights,lev,mp,sl,hold,cd)
                m = calc_metrics(trades) if trades else None
                done2 += 1
                if m:
                    m.update({"factors":label,"lev":lev,"margin":mp,"sl_roe":sl,
                              "hold":hold,"weights":wp_name,"cooldown":cd,
                              "coin_count":len(sh)})
                    results_p2.append(m)
                if done2 % 200 == 0:
                    el=time.time()-t1; rate=done2/el if el>0 else 1
                    print(f"  [{done2}/{total_p2}] {el:.0f}s, ~{(total_p2-done2)/rate:.0f}s left, {len(results_p2)} viable", flush=True)

results_p2.sort(key=lambda x:-x["ev"])
print(f"\nPhase 2 done: {len(results_p2)} viable / {total_p2} tested in {time.time()-t1:.0f}s")

# ═══════════════ FINAL RESULTS ═══════════════
all_results = sorted(results_p1 + results_p2, key=lambda x:-x["ev"])
print(f"\n{'='*80}")
print(f"FINAL: {len(all_results)} total viable configs")
print(f"{'='*80}")
print(f"\nTOP 30 OVERALL:")
print(f"{'#':>3} {'Factors':>8} {'Lev':>4} {'MP':>4} {'SL':>3} {'Hold':>4} {'Wts':>10} {'CD':>3} | {'#T':>4} {'WR%':>5} {'EV$':>7} {'PF':>5} {'WF':>3} {'Ruin%':>6} | {'PnL$':>8}")
print("-"*110)
for i,r in enumerate(all_results[:30]):
    print(f"{i+1:>3} {r['factors']:>8} {r['lev']:>4}x {r['margin']*100:>3.0f}% {r['sl_roe']:>3}% {r['hold']:>4}h {r['weights']:>10} {r['cooldown']:>3}h | "
          f"{r['trades']:>4} {r['wr']:>5.1f} {r['ev']:>7.2f} {r['pf']:>5.2f} {r['wf']:>3}/4 {r['ruin_pct']:>5.1f}% | ${r['total_pnl']:>+8.0f}")

# Safe configs (ruin<10%, WF>=3)
safe = [r for r in all_results if r["ruin_pct"]<10 and r["wf"]>=3]
print(f"\n{'='*80}")
print(f"PRODUCTION-SAFE (ruin<10%, WF>=3): {len(safe)} configs")
print(f"{'='*80}")
for i,r in enumerate(safe[:20]):
    print(f"{i+1:>3} {r['factors']:>8} {r['lev']:>4}x {r['margin']*100:>3.0f}% {r['sl_roe']:>3}% {r['hold']:>4}h {r['weights']:>10} {r['cooldown']:>3}h | "
          f"{r['trades']:>4} {r['wr']:>5.1f} {r['ev']:>7.2f} {r['pf']:>5.2f} {r['wf']:>3}/4 {r['ruin_pct']:>5.1f}% | ${r['total_pnl']:>+8.0f}")

# Save
out = {"phase1_total":total_p1,"phase2_total":total_p2,"viable_total":len(all_results),
       "top100":all_results[:100],"safe_top50":safe[:50]}
Path("quant_runtime/output/ensemble_full_factorial.json").write_text(json.dumps(out,indent=1))
print(f"\nSaved → quant_runtime/output/ensemble_full_factorial.json")
print("Done.", flush=True)
