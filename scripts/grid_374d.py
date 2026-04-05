#!/usr/bin/env python3
"""
374-Day Full Grid Search
========================
9000 bars (374일) 1h 데이터로 처음부터 다시.

이전 실패 원인 반영:
- 58일 과최적화 → 374일 전체에서 검증
- Walk-forward: 전반 250일 in-sample / 후반 124일 out-of-sample
- 비용 시나리오: taker(14bps), maker(6bps), stress(28bps)

전략 카테고리:
A. 추세추종 (다양한 파라미터)
B. 추세 + 레짐 필터 (횡보 감지 → 진입 차단)
C. 롱만 / 숏만 분리
D. 더 넓은 SL (2x, 3x ATR)
E. 더 긴 holding (48h, 72h)
F. 4h 타임프레임
"""
from __future__ import annotations
import json
from pathlib import Path
from collections import defaultdict
import numpy as np

HIST_DIR = Path(__file__).resolve().parent.parent / "quant_runtime" / "historical"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
STOP_FLOOR_BPS = 45.0

def load(sym, tf):
    p = HIST_DIR / sym / f"{tf}.json"
    if not p.exists(): return {}
    with open(p) as f: raw = json.load(f)
    return {
        "t": np.array([c["open_time"] for c in raw], dtype=np.int64),
        "o": np.array([c["open_price"] for c in raw], dtype=np.float64),
        "h": np.array([c["high_price"] for c in raw], dtype=np.float64),
        "l": np.array([c["low_price"] for c in raw], dtype=np.float64),
        "c": np.array([c["close_price"] for c in raw], dtype=np.float64),
        "v": np.array([c["quote_volume"] for c in raw], dtype=np.float64),
    }

# ── Indicators ────────────────────────────────────────
def _ema(a, p):
    r=np.full_like(a,np.nan,dtype=np.float64)
    if len(a)<p: return r
    al=2.0/(p+1); r[p-1]=np.mean(a[:p])
    for i in range(p,len(a)): r[i]=al*a[i]+(1-al)*r[i-1]
    return r

def _sma(a,p):
    r=np.full_like(a,np.nan,dtype=np.float64)
    if len(a)<p: return r
    cs=np.cumsum(a); r[p-1:]=(cs[p-1:]-np.concatenate([[0],cs[:-p]]))/p
    return r

def _atr(h,l,c,p=14):
    r=np.full_like(c,np.nan)
    if len(c)<p+1: return r
    tr=np.maximum(h[1:]-l[1:],np.maximum(np.abs(h[1:]-c[:-1]),np.abs(l[1:]-c[:-1])))
    av=np.full(len(tr),np.nan); av[p-1]=np.mean(tr[:p])
    for i in range(p,len(tr)): av[i]=(av[i-1]*(p-1)+tr[i])/p
    r[1:]=av; return r

def _adx(h,l,c,p=14):
    r=np.full_like(c,np.nan); n=len(c)
    if n<2*p+1: return r
    up=h[1:]-h[:-1]; down=l[:-1]-l[1:]
    pdm=np.where((up>down)&(up>0),up,0.0); mdm=np.where((down>up)&(down>0),down,0.0)
    tr=np.maximum(h[1:]-l[1:],np.maximum(np.abs(h[1:]-c[:-1]),np.abs(l[1:]-c[:-1])))
    st=np.full(len(tr),np.nan);sp=np.full(len(tr),np.nan);sm=np.full(len(tr),np.nan)
    st[p-1]=np.sum(tr[:p]);sp[p-1]=np.sum(pdm[:p]);sm[p-1]=np.sum(mdm[:p])
    for i in range(p,len(tr)):
        st[i]=st[i-1]-st[i-1]/p+tr[i];sp[i]=sp[i-1]-sp[i-1]/p+pdm[i];sm[i]=sm[i-1]-sm[i-1]/p+mdm[i]
    pdi=100*sp/np.where(st==0,1e-10,st);mdi=100*sm/np.where(st==0,1e-10,st)
    dx=100*np.abs(pdi-mdi)/np.where((pdi+mdi)==0,1e-10,pdi+mdi)
    av=np.full(len(dx),np.nan);s2=2*p-1
    if s2<len(dx):
        av[s2]=np.mean(dx[p-1:s2+1])
        for i in range(s2+1,len(dx)): av[i]=(av[i-1]*(p-1)+dx[i])/p
    r[1:]=av; return r

def _rsi(c,p=14):
    r=np.full_like(c,np.nan)
    if len(c)<p+1: return r
    d=np.diff(c);g=np.where(d>0,d,0.0);lo=np.where(d<0,-d,0.0)
    ag=np.full(len(d),np.nan);al=np.full(len(d),np.nan)
    ag[p-1]=np.mean(g[:p]);al[p-1]=np.mean(lo[:p])
    for i in range(p,len(d)):ag[i]=(ag[i-1]*(p-1)+g[i])/p;al[i]=(al[i-1]*(p-1)+lo[i])/p
    rs=ag/np.where(al==0,1e-10,al);r[1:]=100-100/(1+rs)
    return r

def _bb_width(c, p=20):
    """Bollinger Band width as regime filter. Low width = squeeze/range."""
    mid = _sma(c, p)
    std = np.full_like(c, np.nan)
    for i in range(p-1, len(c)):
        std[i] = np.std(c[i-p+1:i+1], ddof=0)
    width = 2 * std / np.where(mid == 0, 1e-10, mid) * 100  # as percentage
    return width

def _vol_sma(v, p=20):
    return _sma(v, p)

# ── Trade engine ──────────────────────────────────────
def _trade(d, i, side, hold, atr_v, sl_mult, rr, cost_bps):
    c,h,l=d["c"],d["h"],d["l"]
    if i>=len(c)-2 or np.isnan(atr_v[i]) or atr_v[i]<=0: return None
    entry=c[i]
    sl_dist=max(sl_mult*atr_v[i], entry*STOP_FLOOR_BPS/10000)
    tp_dist=rr*sl_dist; sl_bps=sl_dist/entry*10000
    if side=="long": sl_p=entry-sl_dist;tp_p=entry+tp_dist
    else: sl_p=entry+sl_dist;tp_p=entry-tp_dist
    exit_idx=min(i+hold,len(c)-1); reason="TIME"
    for j in range(i+1,exit_idx+1):
        if side=="long":
            if l[j]<=sl_p: exit_idx=j;reason="SL";break
            if h[j]>=tp_p: exit_idx=j;reason="TP";break
        else:
            if h[j]>=sl_p: exit_idx=j;reason="SL";break
            if l[j]<=tp_p: exit_idx=j;reason="TP";break
    ep=sl_p if reason=="SL" else (tp_p if reason=="TP" else c[exit_idx])
    raw=(ep-entry)/entry*10000 if side=="long" else (entry-ep)/entry*10000
    return {"net":raw-cost_bps,"reason":reason,"bars":exit_idx-i}

def _trade_partial(d, i, side, hold, atr_v, sl_mult, rr1, rr2, cost_bps):
    c,h,l=d["c"],d["h"],d["l"]
    if i>=len(c)-2 or np.isnan(atr_v[i]) or atr_v[i]<=0: return None
    entry=c[i]
    sl_dist=max(sl_mult*atr_v[i], entry*STOP_FLOOR_BPS/10000)
    tp1=rr1*sl_dist;tp2=rr2*sl_dist
    if side=="long": sl_p=entry-sl_dist;tp1_p=entry+tp1;tp2_p=entry+tp2
    else: sl_p=entry+sl_dist;tp1_p=entry-tp1;tp2_p=entry-tp2
    exit_idx=min(i+hold,len(c)-1);half=False;half_bps=0;be=entry
    for j in range(i+1,exit_idx+1):
        if not half:
            if side=="long":
                if l[j]<=sl_p: return {"net":(sl_p-entry)/entry*10000-cost_bps,"reason":"SL","bars":j-i}
                if h[j]>=tp1_p: half_bps=(tp1_p-entry)/entry*10000*0.5;half=True;be=entry+sl_dist*0.1
            else:
                if h[j]>=sl_p: return {"net":(entry-sl_p)/entry*10000-cost_bps,"reason":"SL","bars":j-i}
                if l[j]<=tp1_p: half_bps=(entry-tp1_p)/entry*10000*0.5;half=True;be=entry-sl_dist*0.1
        else:
            if side=="long":
                if l[j]<=be: r2=(be-entry)/entry*10000*0.5;return {"net":half_bps+r2-cost_bps,"reason":"BE","bars":j-i}
                if h[j]>=tp2_p: r2=(tp2_p-entry)/entry*10000*0.5;return {"net":half_bps+r2-cost_bps,"reason":"TP2","bars":j-i}
            else:
                if h[j]>=be: r2=(entry-be)/entry*10000*0.5;return {"net":half_bps+r2-cost_bps,"reason":"BE","bars":j-i}
                if l[j]<=tp2_p: r2=(entry-tp2_p)/entry*10000*0.5;return {"net":half_bps+r2-cost_bps,"reason":"TP2","bars":j-i}
    ep=c[exit_idx]
    if half: r2=((ep-entry)/entry*10000 if side=="long" else (entry-ep)/entry*10000)*0.5;net=half_bps+r2-cost_bps
    else: net=((ep-entry)/entry*10000 if side=="long" else (entry-ep)/entry*10000)-cost_bps
    return {"net":net,"reason":"TIME","bars":exit_idx-i}

# ── Strategy runners ──────────────────────────────────
def run_ema_cross(d, *, fast, slow, hold, adx_min, sl_mult, rr, cost_bps,
                  side_filter="both", regime_filter=False, bb_width_min=0):
    c=d["c"];ef=_ema(c,fast);es=_ema(c,slow);ax=_adx(d["h"],d["l"],c);at=_atr(d["h"],d["l"],c)
    bbw = _bb_width(c) if regime_filter else None
    trades=[];i=max(slow+1,55)
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [ef,es,ax,at]) or any(np.isnan(x[i-1]) for x in [ef,es]):
            i+=1;continue
        if ax[i]<adx_min: i+=1;continue
        if regime_filter and bbw is not None and not np.isnan(bbw[i]) and bbw[i]<bb_width_min:
            i+=1;continue
        up=ef[i-1]<=es[i-1] and ef[i]>es[i];dn=ef[i-1]>=es[i-1] and ef[i]<es[i]
        side=None
        if up and side_filter in ("both","long"): side="long"
        elif dn and side_filter in ("both","short"): side="short"
        if side:
            t=_trade(d,i,side,hold,at,sl_mult,rr,cost_bps)
            if t: trades.append(t);i+=t["bars"]+1
            else: i+=1
        else: i+=1
    return trades

def run_ema_partial(d, *, fast, slow, hold, adx_min, sl_mult, rr1, rr2, cost_bps,
                    side_filter="both", regime_filter=False, bb_width_min=0):
    c=d["c"];ef=_ema(c,fast);es=_ema(c,slow);ax=_adx(d["h"],d["l"],c);at=_atr(d["h"],d["l"],c)
    bbw = _bb_width(c) if regime_filter else None
    trades=[];i=max(slow+1,55)
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [ef,es,ax,at]) or any(np.isnan(x[i-1]) for x in [ef,es]):
            i+=1;continue
        if ax[i]<adx_min: i+=1;continue
        if regime_filter and bbw is not None and not np.isnan(bbw[i]) and bbw[i]<bb_width_min:
            i+=1;continue
        up=ef[i-1]<=es[i-1] and ef[i]>es[i];dn=ef[i-1]>=es[i-1] and ef[i]<es[i]
        side=None
        if up and side_filter in ("both","long"): side="long"
        elif dn and side_filter in ("both","short"): side="short"
        if side:
            t=_trade_partial(d,i,side,hold,at,sl_mult,rr1,rr2,cost_bps)
            if t: trades.append(t);i+=t["bars"]+1
            else: i+=1
        else: i+=1
    return trades

def run_pullback(d, *, ema_p, hold, adx_min, sl_mult, rr, cost_bps, rsi_entry, side_filter="both"):
    c=d["c"];e=_ema(c,ema_p);e50=_ema(c,50);r=_rsi(c);ax=_adx(d["h"],d["l"],c);at=_atr(d["h"],d["l"],c)
    trades=[];i=55
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [e,e50,r,ax,at]) or np.isnan(r[i-1]):
            i+=1;continue
        if ax[i]<adx_min: i+=1;continue
        side=None
        if c[i]>e50[i] and e[i]>e50[i] and r[i-1]<rsi_entry and r[i]>=rsi_entry and r[i]<60 and side_filter in ("both","long"):
            side="long"
        elif c[i]<e50[i] and e[i]<e50[i] and r[i-1]>(100-rsi_entry) and r[i]<=(100-rsi_entry) and r[i]>40 and side_filter in ("both","short"):
            side="short"
        if side:
            t=_trade(d,i,side,hold,at,sl_mult,rr,cost_bps)
            if t: trades.append(t);i+=t["bars"]+1
            else: i+=1
        else: i+=1
    return trades

def run_rsi_50_cross(d, *, hold, adx_min, sl_mult, rr, cost_bps, side_filter="both", vol_filter=False):
    c=d["c"];r=_rsi(c);ax=_adx(d["h"],d["l"],c);at=_atr(d["h"],d["l"],c);e50=_ema(c,50)
    vs=_vol_sma(d["v"],20) if vol_filter else None
    trades=[];i=55
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [r,ax,at,e50]) or np.isnan(r[i-1]):
            i+=1;continue
        if ax[i]<adx_min: i+=1;continue
        if vol_filter and vs is not None and (np.isnan(vs[i]) or d["v"][i]<vs[i]*0.8):
            i+=1;continue
        side=None
        if r[i-1]<50 and r[i]>=50 and c[i]>e50[i] and side_filter in ("both","long"): side="long"
        elif r[i-1]>50 and r[i]<=50 and c[i]<e50[i] and side_filter in ("both","short"): side="short"
        if side:
            t=_trade(d,i,side,hold,at,sl_mult,rr,cost_bps)
            if t: trades.append(t);i+=t["bars"]+1
            else: i+=1
        else: i+=1
    return trades

# ── MC ────────────────────────────────────────────────
def mc_ruin(rets, n_sims=5000, n_per=200):
    if len(rets)<3: return 1.0
    ret=np.array(rets);rng=np.random.default_rng(42);rc=0
    thr=-3000  # -30% in bps terms
    for _ in range(n_sims):
        s=rng.choice(ret,n_per,replace=True);eq=np.cumsum(s);pk=np.maximum.accumulate(eq)
        if np.min(eq-pk)<thr: rc+=1
    return rc/n_sims

# ── Stats ─────────────────────────────────────────────
def stats(trades):
    if not trades: return None
    nets=[t["net"] for t in trades];n=len(nets);wins=sum(1 for x in nets if x>0)
    gp=sum(x for x in nets if x>0);gl=abs(sum(x for x in nets if x<0))
    pf=gp/gl if gl>0 else (999 if gp>0 else 0)
    return {"n":n,"wr":wins/n,"pf":min(pf,999),"tot":sum(nets),"avg":float(np.mean(nets)),
            "sharpe":float(np.mean(nets)/np.std(nets,ddof=1)) if n>1 and np.std(nets,ddof=1)>0 else 0}

# ── MAIN ──────────────────────────────────────────────
def main():
    print("="*100)
    print("374-DAY FULL GRID SEARCH — 9000 bars, from scratch")
    print("="*100)

    cost_scenarios = {"taker":14.0, "maker":6.0, "stress":28.0}

    # Parameter grid
    configs = []

    # A. EMA Cross variants
    for fast,slow in [(9,21),(12,26),(20,50),(8,21),(10,21)]:
        for hold in [12,18,24,36,48,72]:
            for adx_min in [20,25,28,30,35]:
                for sl_mult in [1.5,2.0,2.5,3.0]:
                    for rr in [1.5,2.0,2.5,3.0]:
                        for sf in ["both","long"]:
                            configs.append(("EMA", "run_ema_cross", {
                                "fast":fast,"slow":slow,"hold":hold,"adx_min":adx_min,
                                "sl_mult":sl_mult,"rr":rr,"side_filter":sf,
                            }))

    # B. EMA Cross + regime filter (BB width)
    for fast,slow in [(9,21),(12,26)]:
        for hold in [18,24,48]:
            for adx_min in [25,28,30]:
                for sl_mult in [2.0,2.5]:
                    for rr in [2.0,2.5]:
                        for bbw_min in [2.0,3.0,4.0]:
                            configs.append(("EMA_REG", "run_ema_cross", {
                                "fast":fast,"slow":slow,"hold":hold,"adx_min":adx_min,
                                "sl_mult":sl_mult,"rr":rr,"regime_filter":True,"bb_width_min":bbw_min,
                            }))

    # C. Partial TP
    for fast,slow in [(9,21),(12,26)]:
        for hold in [24,36,48]:
            for adx_min in [25,28,30]:
                for sl_mult in [2.0,2.5,3.0]:
                    for rr1,rr2 in [(1.0,2.5),(1.0,3.0),(1.5,3.0)]:
                        configs.append(("PARTIAL", "run_ema_partial", {
                            "fast":fast,"slow":slow,"hold":hold,"adx_min":adx_min,
                            "sl_mult":sl_mult,"rr1":rr1,"rr2":rr2,
                        }))

    # D. Pullback
    for ema_p in [21,50]:
        for hold in [18,24,36]:
            for adx_min in [22,25,28]:
                for sl_mult in [2.0,2.5]:
                    for rr in [2.0,2.5,3.0]:
                        for rsi_e in [40,45]:
                            configs.append(("PULLBK", "run_pullback", {
                                "ema_p":ema_p,"hold":hold,"adx_min":adx_min,
                                "sl_mult":sl_mult,"rr":rr,"rsi_entry":rsi_e,
                            }))

    # E. RSI 50 cross
    for hold in [18,24,36]:
        for adx_min in [22,25,28,30]:
            for sl_mult in [2.0,2.5]:
                for rr in [2.0,2.5,3.0]:
                    for sf in ["both","long"]:
                        configs.append(("RSI50", "run_rsi_50_cross", {
                            "hold":hold,"adx_min":adx_min,"sl_mult":sl_mult,"rr":rr,"side_filter":sf,
                        }))

    print(f"총 파라미터 조합: {len(configs)}")

    runners = {
        "run_ema_cross": run_ema_cross,
        "run_ema_partial": run_ema_partial,
        "run_pullback": run_pullback,
        "run_rsi_50_cross": run_rsi_50_cross,
    }

    # Results: (name, sym, params, full_stats, in_stats, out_stats, cost_label)
    eligible = []
    total_tested = 0

    for sym in SYMBOLS:
        d1h = load(sym, "1h")
        if not d1h: continue
        n_bars = len(d1h["c"])
        split = int(n_bars * 0.67)  # 250d in / 124d out
        d_in = {k: v[:split] for k, v in d1h.items()}
        d_out = {k: v[split:] for k, v in d1h.items()}

        print(f"\n  {sym}: {n_bars} bars, split at {split} (in={split}, out={n_bars-split})")

        sym_count = 0
        sym_pass = 0

        for name, fn_name, params in configs:
            fn = runners[fn_name]
            for cost_label, cost_bps in [("taker", 14.0)]:  # Primary screen with taker cost
                trades_full = fn(d1h, cost_bps=cost_bps, **params)
                s_full = stats(trades_full)
                total_tested += 1
                sym_count += 1
                if not s_full or s_full["n"] < 20 or s_full["pf"] <= 1.15 or s_full["wr"] <= 0.35:
                    continue

                # Walk-forward
                trades_in = fn(d_in, cost_bps=cost_bps, **params)
                trades_out = fn(d_out, cost_bps=cost_bps, **params)
                s_in = stats(trades_in)
                s_out = stats(trades_out)
                if not s_out or s_out["n"] < 5 or s_out["pf"] <= 1.0:
                    continue

                # MC ruin on full period
                mc = mc_ruin([t["net"] for t in trades_full])
                if mc > 0.05:
                    continue

                # Stress test
                trades_stress = fn(d1h, cost_bps=28.0, **params)
                s_stress = stats(trades_stress)
                stress_ok = s_stress and s_stress["pf"] > 1.0

                sym_pass += 1
                eligible.append({
                    "name": name, "sym": sym, "params": params,
                    "full": s_full, "in": s_in, "out": s_out,
                    "mc_ruin": mc, "stress_pf": s_stress["pf"] if s_stress else 0,
                    "stress_ok": stress_ok,
                })

        print(f"    Tested: {sym_count}, Passed: {sym_pass}")

    # ── Results ───────────────────────────────────
    print(f"\n\n{'='*100}")
    print(f"  RESULTS — {total_tested} combos tested, {len(eligible)} passed all gates")
    print(f"  Gates: n>=20, PF>1.15, WR>35%, WF out PF>1.0 n>=5, MC ruin<5%")
    print(f"{'='*100}")

    eligible.sort(key=lambda x: x["full"]["pf"], reverse=True)

    if eligible:
        print(f"\n{'Name':<10} {'Sym':<10} {'N':>4} {'WR':>5} {'PF':>6} {'TotBps':>8} {'AvgBps':>7} {'Shrp':>6} {'MCR':>5} {'OutPF':>6} {'OutN':>5} {'StrPF':>6}  Params")
        print(f"{'─'*130}")
        for e in eligible[:60]:
            s = e["full"]; o = e["out"]
            pf_s = f"{s['pf']:.2f}" if s['pf'] < 100 else "inf"
            opf = f"{o['pf']:.2f}" if o['pf'] < 100 else "inf"
            spf = f"{e['stress_pf']:.2f}" if e['stress_pf'] < 100 else "inf"
            stag = "" if e["stress_ok"] else " [stress FAIL]"
            ps = ", ".join(f"{k}={v}" for k,v in e["params"].items() if v not in (False,"both",0))
            print(f"{e['name']:<10} {e['sym']:<10} {s['n']:>4} {s['wr']:>4.0%} {pf_s:>6} {s['tot']:>8.0f} {s['avg']:>7.1f} {s['sharpe']:>6.3f} {e['mc_ruin']:>4.0%} {opf:>6} {o['n']:>5} {spf:>6}{stag}  {ps}")
    else:
        print("\n  NO STRATEGIES PASSED ALL GATES.")
        print("\n  Showing best near-misses (PF>1.05, n>=15):")
        near = []
        # Re-scan for near misses with relaxed criteria
        for sym in SYMBOLS:
            d1h = load(sym, "1h")
            if not d1h: continue
            for name, fn_name, params in configs[:500]:  # sample
                fn = runners[fn_name]
                trades = fn(d1h, cost_bps=14.0, **params)
                s = stats(trades)
                if s and s["n"] >= 15 and s["pf"] > 1.05:
                    near.append((name, sym, params, s))
        near.sort(key=lambda x: x[3]["pf"], reverse=True)
        for name, sym, params, s in near[:20]:
            ps = ", ".join(f"{k}={v}" for k,v in params.items() if v not in (False,"both",0))
            print(f"  {name:<10} {sym:<10} n={s['n']:>3} WR={s['wr']:.0%} PF={s['pf']:.2f} Tot={s['tot']:.0f}bps  {ps}")

    # ── Cross-symbol consistency ──────────────────
    if eligible:
        print(f"\n\n{'='*100}")
        print("  CROSS-SYMBOL (3+ symbols)")
        print(f"{'='*100}")
        groups = defaultdict(list)
        for e in eligible:
            key = (e["name"], json.dumps(e["params"], sort_keys=True))
            groups[key].append(e)
        multi = [(k,v) for k,v in groups.items() if len(v) >= 2]
        multi.sort(key=lambda x: np.mean([e["full"]["pf"] for e in x[1]]), reverse=True)
        for (name, pj), entries in multi[:10]:
            params = json.loads(pj)
            avg_pf = np.mean([e["full"]["pf"] for e in entries])
            syms = [e["sym"] for e in entries]
            print(f"\n  {name} | avg PF={avg_pf:.2f} | {', '.join(syms)}")
            for e in entries:
                s = e["full"]; o = e["out"]
                print(f"    {e['sym']}: n={s['n']} WR={s['wr']:.0%} PF={s['pf']:.2f} Out={o['pf']:.2f}({o['n']}) MC={e['mc_ruin']:.0%}")

    # Save
    out = Path(__file__).resolve().parent.parent / "quant_runtime" / "output" / "signal_research"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "v7_374d_grid.json", "w") as f:
        json.dump([{k: (round(v,4) if isinstance(v,float) else v) for k,v in e.items() if k!="params"} | {"params": e["params"]}
                   for e in eligible[:100]], f, indent=2, default=str)
    print(f"\n결과 저장: {out / 'v7_374d_grid.json'}")


if __name__ == "__main__":
    main()
