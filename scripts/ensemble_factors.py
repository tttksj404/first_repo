"""Individual factor backtests + ensemble combination.

Tests 5 factors independently, then combines winners.
A. Vol-managed momentum
B. Cross-sectional winner rotation
C. Short-term reversal (buy crash dips)
D. Regime detection
E. BTC-residual strength
"""
import json, random, statistics
from pathlib import Path

dd = Path("quant_runtime/historical")
COST_RT=0.0012; EQUITY=75.0

def ema_arr(c,p):
    e=[0.0]*len(c);e[0]=c[0];k=2/(p+1)
    for i in range(1,len(c)):e[i]=c[i]*k+e[i-1]*(1-k)
    return e

# Load all coins
all_coins = {}
for sym_dir in sorted(dd.iterdir()):
    if not sym_dir.is_dir(): continue
    sym = sym_dir.name; p1h = sym_dir/"1h.json"
    if not p1h.exists(): continue
    b1 = json.load(open(p1h))
    if len(b1) < 10000: continue
    all_coins[sym] = [b["close_price"] for b in b1]

btc = all_coins.get("BTCUSDT", [])
n = min(len(c) for c in all_coins.values())
syms = sorted(all_coins.keys())
print(f"Loaded {len(syms)} coins, {n} bars ({n/24:.0f}d)", flush=True)

# ── Factor A: Vol-Managed Momentum ──
def factor_a_signal(c, i, lookback=168):
    """Return momentum score scaled by inverse volatility."""
    if i < lookback + 50: return 0
    mom = (c[i] - c[i-lookback]) / c[i-lookback]
    rets = [(c[i-j] - c[i-j-1]) / c[i-j-1] for j in range(1, min(240, i))]
    vol = statistics.stdev(rets) if len(rets) > 10 else 1
    if vol < 0.0001: return 0
    return mom / vol  # vol-adjusted momentum

# ── Factor B: Cross-Sectional Rank ──
def factor_b_ranks(all_c, i, lookback=168):
    """Rank coins by raw momentum, return dict of ranks."""
    moms = {}
    for sym, c in all_c.items():
        if i >= len(c) or i < lookback: continue
        moms[sym] = (c[i] - c[i-lookback]) / c[i-lookback]
    ranked = sorted(moms.items(), key=lambda x: -x[1])
    return {sym: rank for rank, (sym, _) in enumerate(ranked)}

# ── Factor C: Short-Term Reversal ──
def factor_c_signal(c, i, lookback=72):
    """Buy signal after extreme 3-day drop."""
    if i < lookback: return 0
    ret_3d = (c[i] - c[i-lookback]) / c[i-lookback]
    if ret_3d < -0.10:  # dropped 10%+ in 3 days
        return 1  # buy signal
    return 0

# ── Factor D: Regime ──
def detect_regime(btc_c, i):
    """0=crash, 1=range, 2=trend"""
    if i < 720: return 1
    ret_5d = (btc_c[i] - btc_c[i-120]) / btc_c[i-120]
    rets = [(btc_c[i-j] - btc_c[i-j-1]) / btc_c[i-j-1] for j in range(1, min(240, i))]
    vol = statistics.stdev(rets) if len(rets) > 10 else 0.01
    vol_pct = sorted(rets)
    vol_95 = abs(vol_pct[int(len(vol_pct)*0.05)]) if len(vol_pct)>20 else 0.05

    if ret_5d < -0.08: return 0  # crash
    e20 = sum(btc_c[max(0,i-20):i+1]) / min(20, i+1)
    e50 = sum(btc_c[max(0,i-50):i+1]) / min(50, i+1)
    if e20 > e50: return 2  # trend
    return 1  # range

# ── Factor E: BTC-Residual Strength ──
def factor_e_signal(c, btc_c, i, lookback=168):
    """Return excess return vs BTC."""
    if i < lookback or i >= len(btc_c): return 0
    coin_ret = (c[i] - c[i-lookback]) / c[i-lookback]
    btc_ret = (btc_c[i] - btc_c[i-lookback]) / btc_c[i-lookback]
    return coin_ret - btc_ret

# ── Run each factor individually ──
print("\n=== INDIVIDUAL FACTOR BACKTESTS ===", flush=True)

for factor_name, use_factors in [
    ("A_vol_mom", [True,False,False,False,False]),
    ("B_xsect", [False,True,False,False,False]),
    ("C_reversal", [False,False,True,False,False]),
    ("E_btc_resid", [False,False,False,False,True]),
    ("ENSEMBLE_all", [True,True,True,True,True]),
]:
    for lev in [5, 10]:
      for mp in [0.50, 0.75]:
        margin = EQUITY * mp; notional = margin * lev; fee = notional * COST_RT

        trades = []; pos = None; cd = 0
        for i in range(720, n, 24):  # check daily (every 24 bars)
            if pos:
                c = all_coins[pos["sym"]]
                if i >= len(c): pos = None; continue
                pc = (c[i]/pos["bp"]-1); roe = pc*100*lev
                hh = i - pos["ei"]; fd = notional*0.0001*(hh//8)
                # SL 15% ROE
                if roe <= -15:
                    trades.append(margin*(-15/100)-fee-fd); pos=None; cd=i+48; continue
                # Hold 1 week then exit
                if hh >= 168:
                    trades.append(margin*(roe/100)-fee-fd); pos=None; continue
                continue

            if i < cd: continue
            regime = detect_regime(btc, i) if use_factors[3] else 2  # default trend
            if regime == 0: continue  # crash → skip

            # Score each coin
            scores = {}
            ranks = factor_b_ranks(all_coins, i) if use_factors[1] else {}

            for sym, c in all_coins.items():
                if sym == "BTCUSDT": continue  # don't trade BTC directly
                if i >= len(c): continue
                score = 0
                # A: vol-managed momentum
                if use_factors[0]:
                    a = factor_a_signal(c, i)
                    weight_a = 1.5 if regime == 2 else 0.5  # higher in trend
                    score += a * weight_a
                # B: cross-sectional rank
                if use_factors[1] and sym in ranks:
                    rank_score = 1.0 - ranks[sym] / max(len(ranks), 1)
                    weight_b = 1.0 if regime == 1 else 0.7  # higher in range
                    score += rank_score * weight_b
                # C: reversal
                if use_factors[2]:
                    rev = factor_c_signal(c, i)
                    weight_c = 1.5 if regime == 1 else 0.3  # higher in range
                    score += rev * weight_c
                # E: BTC residual
                if use_factors[4]:
                    e = factor_e_signal(c, btc, i)
                    score += e * 2.0
                scores[sym] = score

            if not scores: continue
            # Pick top coin with positive score
            best = max(scores.items(), key=lambda x: x[1])
            if best[1] <= 0: continue

            pos = {"sym": best[0], "bp": all_coins[best[0]][i], "ei": i}

        if not trades or len(trades) < 10: continue
        w=sum(1 for t in trades if t>0); nt=len(trades); total=sum(trades)
        if total <= 0: continue
        gp=sum(t for t in trades if t>0); gl=abs(sum(t for t in trades if t<=0))
        pf=gp/max(gl,0.01); wr=w/max(nt,1); aw=gp/max(w,1); al=gl/max(nt-w,1)
        ev=wr*aw-(1-wr)*al; tpm=nt/1090*30
        fs=max(nt//4,1); wf=sum(1 for fi in range(4) if sum(trades[fi*fs:(fi+1)*fs if fi<3 else nt])>0)
        ruin=0
        for _ in range(1000):
            bal=75.0
            for t in random.choices(trades,k=nt):
                bal+=t
                if bal<=0:ruin+=1;break
        print(f"  {factor_name:>15} {lev}x {mp*100:.0f}%: {nt:>4}t({tpm:.0f}/mo) WR={wr*100:.0f}% aw=${aw:.2f} EV=${ev:.2f} ruin={ruin/10:.1f}% PF={pf:.2f} WF={wf}/4 PnL=${total:+.0f}", flush=True)

print("\nDone.", flush=True)
