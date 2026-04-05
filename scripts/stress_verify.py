#!/usr/bin/env python3
"""
Stress Verification — 라이브 편입 전 최종 검증
==============================================

검증 항목:
1. Trade-by-trade 상세 출력 (날짜, 방향, 진입가, 청산가, 이유)
2. Walk-forward: 전반 30일 in-sample → 후반 28일 out-of-sample
3. 비용 스트레스: slippage 2배, fee 2배에서도 수익인지
4. 연속 손실 최대 횟수
5. 최대 연속 손실 금액
6. 교차상관: 심볼 간 동시 진입 빈도 (과집중 위험)
7. 월별 수익 분포 (특정 기간 편중 여부)
8. 롱/숏 비대칭
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

import numpy as np

HIST_DIR = Path(__file__).resolve().parent.parent / "quant_runtime" / "historical"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
BASE_FEE_BPS = 4.0
BASE_SLIP_BPS = 3.0
ATR_STOP_MULT = 1.5
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


# ── Indicators (compact) ─────────────────────────────
def _ema(a, p):
    r = np.full_like(a, np.nan, dtype=np.float64)
    if len(a) < p: return r
    al = 2.0/(p+1); r[p-1] = np.mean(a[:p])
    for i in range(p, len(a)): r[i] = al*a[i] + (1-al)*r[i-1]
    return r

def _atr(h, l, c, p=14):
    r = np.full_like(c, np.nan)
    if len(c) < p+1: return r
    tr = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    av = np.full(len(tr), np.nan); av[p-1]=np.mean(tr[:p])
    for i in range(p, len(tr)): av[i]=(av[i-1]*(p-1)+tr[i])/p
    r[1:]=av; return r

def _adx(h, l, c, p=14):
    r = np.full_like(c, np.nan); n = len(c)
    if n < 2*p+1: return r
    up=h[1:]-h[:-1]; down=l[:-1]-l[1:]
    pdm=np.where((up>down)&(up>0),up,0.0); mdm=np.where((down>up)&(down>0),down,0.0)
    tr=np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    st=np.full(len(tr),np.nan); sp=np.full(len(tr),np.nan); sm=np.full(len(tr),np.nan)
    st[p-1]=np.sum(tr[:p]); sp[p-1]=np.sum(pdm[:p]); sm[p-1]=np.sum(mdm[:p])
    for i in range(p, len(tr)):
        st[i]=st[i-1]-st[i-1]/p+tr[i]; sp[i]=sp[i-1]-sp[i-1]/p+pdm[i]; sm[i]=sm[i-1]-sm[i-1]/p+mdm[i]
    pdi=100*sp/np.where(st==0,1e-10,st); mdi=100*sm/np.where(st==0,1e-10,st)
    dx=100*np.abs(pdi-mdi)/np.where((pdi+mdi)==0,1e-10,pdi+mdi)
    av=np.full(len(dx),np.nan); s2=2*p-1
    if s2<len(dx):
        av[s2]=np.mean(dx[p-1:s2+1])
        for i in range(s2+1, len(dx)): av[i]=(av[i-1]*(p-1)+dx[i])/p
    r[1:]=av; return r

def _rsi(c, p=14):
    r=np.full_like(c, np.nan)
    if len(c)<p+1: return r
    d=np.diff(c); g=np.where(d>0,d,0.0); lo=np.where(d<0,-d,0.0)
    ag=np.full(len(d),np.nan); al=np.full(len(d),np.nan)
    ag[p-1]=np.mean(g[:p]); al[p-1]=np.mean(lo[:p])
    for i in range(p,len(d)): ag[i]=(ag[i-1]*(p-1)+g[i])/p; al[i]=(al[i-1]*(p-1)+lo[i])/p
    rs=ag/np.where(al==0,1e-10,al); r[1:]=100-100/(1+rs)
    return r

def _sma(a, p):
    r = np.full_like(a, np.nan, dtype=np.float64)
    if len(a)<p: return r
    cs=np.cumsum(a); r[p-1:]=(cs[p-1:]-np.concatenate([[0],cs[:-p]]))/p
    return r


# ── Trade execution ───────────────────────────────────
def _exec_partial(d, i, side, hold, atr_v, rr1, rr2, cost_bps):
    c,h,l = d["c"], d["h"], d["l"]
    if i>=len(c)-2 or np.isnan(atr_v[i]) or atr_v[i]<=0: return None
    entry=c[i]
    sl_dist=max(ATR_STOP_MULT*atr_v[i], entry*STOP_FLOOR_BPS/10000)
    tp1_dist=rr1*sl_dist; tp2_dist=rr2*sl_dist
    sl_bps=sl_dist/entry*10000

    if side=="long": sl_p=entry-sl_dist; tp1_p=entry+tp1_dist; tp2_p=entry+tp2_dist
    else: sl_p=entry+sl_dist; tp1_p=entry-tp1_dist; tp2_p=entry-tp2_dist

    exit_idx=min(i+hold, len(c)-1); half=False; half_bps=0.0; be_stop=entry

    for j in range(i+1, exit_idx+1):
        if not half:
            if side=="long":
                if l[j]<=sl_p: raw=(sl_p-entry)/entry*10000; return {"side":side,"entry":entry,"exit":sl_p,"net":raw-cost_bps,"sl_bps":sl_bps,"reason":"SL","bars":j-i,"idx":i,"ts":int(d["t"][i])}
                if h[j]>=tp1_p: half_bps=(tp1_p-entry)/entry*10000*0.5; half=True; be_stop=entry+sl_dist*0.1
            else:
                if h[j]>=sl_p: raw=(entry-sl_p)/entry*10000; return {"side":side,"entry":entry,"exit":sl_p,"net":raw-cost_bps,"sl_bps":sl_bps,"reason":"SL","bars":j-i,"idx":i,"ts":int(d["t"][i])}
                if l[j]<=tp1_p: half_bps=(entry-tp1_p)/entry*10000*0.5; half=True; be_stop=entry-sl_dist*0.1
        else:
            if side=="long":
                if l[j]<=be_stop: raw2=(be_stop-entry)/entry*10000*0.5; return {"side":side,"entry":entry,"exit":be_stop,"net":half_bps+raw2-cost_bps,"sl_bps":sl_bps,"reason":"BE","bars":j-i,"idx":i,"ts":int(d["t"][i])}
                if h[j]>=tp2_p: raw2=(tp2_p-entry)/entry*10000*0.5; return {"side":side,"entry":entry,"exit":tp2_p,"net":half_bps+raw2-cost_bps,"sl_bps":sl_bps,"reason":"TP2","bars":j-i,"idx":i,"ts":int(d["t"][i])}
            else:
                if h[j]>=be_stop: raw2=(entry-be_stop)/entry*10000*0.5; return {"side":side,"entry":entry,"exit":be_stop,"net":half_bps+raw2-cost_bps,"sl_bps":sl_bps,"reason":"BE","bars":j-i,"idx":i,"ts":int(d["t"][i])}
                if l[j]<=tp2_p: raw2=(entry-tp2_p)/entry*10000*0.5; return {"side":side,"entry":entry,"exit":tp2_p,"net":half_bps+raw2-cost_bps,"sl_bps":sl_bps,"reason":"TP2","bars":j-i,"idx":i,"ts":int(d["t"][i])}

    ep=c[exit_idx]
    if half: raw2=((ep-entry)/entry*10000 if side=="long" else (entry-ep)/entry*10000)*0.5; net=half_bps+raw2-cost_bps
    else: net=((ep-entry)/entry*10000 if side=="long" else (entry-ep)/entry*10000)-cost_bps
    return {"side":side,"entry":entry,"exit":ep,"net":net,"sl_bps":sl_bps,"reason":"TIME","bars":exit_idx-i,"idx":i,"ts":int(d["t"][i])}


def _exec_simple(d, i, side, hold, atr_v, rr, cost_bps):
    c,h,l = d["c"], d["h"], d["l"]
    if i>=len(c)-2 or np.isnan(atr_v[i]) or atr_v[i]<=0: return None
    entry=c[i]
    sl_dist=max(ATR_STOP_MULT*atr_v[i], entry*STOP_FLOOR_BPS/10000)
    tp_dist=rr*sl_dist; sl_bps=sl_dist/entry*10000
    if side=="long": sl_p=entry-sl_dist; tp_p=entry+tp_dist
    else: sl_p=entry+sl_dist; tp_p=entry-tp_dist
    exit_idx=min(i+hold, len(c)-1); reason="TIME"
    for j in range(i+1, exit_idx+1):
        if side=="long":
            if l[j]<=sl_p: exit_idx=j; reason="SL"; break
            if h[j]>=tp_p: exit_idx=j; reason="TP"; break
        else:
            if h[j]>=sl_p: exit_idx=j; reason="SL"; break
            if l[j]<=tp_p: exit_idx=j; reason="TP"; break
    ep = sl_p if reason=="SL" else (tp_p if reason=="TP" else c[exit_idx])
    raw = (ep-entry)/entry*10000 if side=="long" else (entry-ep)/entry*10000
    return {"side":side,"entry":entry,"exit":ep,"net":raw-cost_bps,"sl_bps":sl_bps,"reason":reason,"bars":exit_idx-i,"idx":i,"ts":int(d["t"][i])}


# ── Strategy runners ──────────────────────────────────
def run_ema_partial(d, cost_bps, fast=9, slow=21, hold=24, adx_min=28, rr1=1.0, rr2=2.5):
    c=d["c"]; ef=_ema(c,fast); es=_ema(c,slow); ax=_adx(d["h"],d["l"],c); at=_atr(d["h"],d["l"],c)
    trades=[]; i=max(slow+1,30)
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [ef,es,ax,at]) or any(np.isnan(x[i-1]) for x in [ef,es]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        up=ef[i-1]<=es[i-1] and ef[i]>es[i]; dn=ef[i-1]>=es[i-1] and ef[i]<es[i]
        if up or dn:
            t=_exec_partial(d, i, "long" if up else "short", hold, at, rr1, rr2, cost_bps)
            if t: trades.append(t); i+=t["bars"]+1
            else: i+=1
        else: i+=1
    return trades

def run_rsi_trend(d, cost_bps, hold=12, adx_min=28, rr=2.0):
    c=d["c"]; r=_rsi(c); ax=_adx(d["h"],d["l"],c); at=_atr(d["h"],d["l"],c); e50=_ema(c,50)
    trades=[]; i=55
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [r,ax,at,e50]) or np.isnan(r[i-1]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        if r[i-1]<50 and r[i]>=50 and c[i]>e50[i]:
            t=_exec_simple(d, i, "long", hold, at, rr, cost_bps)
            if t: trades.append(t); i+=t["bars"]+1
            else: i+=1
        elif r[i-1]>50 and r[i]<=50 and c[i]<e50[i]:
            t=_exec_simple(d, i, "short", hold, at, rr, cost_bps)
            if t: trades.append(t); i+=t["bars"]+1
            else: i+=1
        else: i+=1
    return trades

def run_ema_ribbon(d, cost_bps, hold=12, adx_min=28, rr=1.5):
    c=d["c"]; e8=_ema(c,8); e13=_ema(c,13); e21=_ema(c,21)
    ax=_adx(d["h"],d["l"],c); at=_atr(d["h"],d["l"],c)
    trades=[]; i=30
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [e8,e13,e21,ax,at]) or any(np.isnan(x[i-1]) for x in [e8,e13,e21]):
            i+=1; continue
        if ax[i]<adx_min: i+=1; continue
        bull=e8[i]>e13[i]>e21[i]; bear=e8[i]<e13[i]<e21[i]
        prev_not_bull=not(e8[i-1]>e13[i-1]>e21[i-1]); prev_not_bear=not(e8[i-1]<e13[i-1]<e21[i-1])
        if bull and prev_not_bull:
            t=_exec_simple(d, i, "long", hold, at, rr, cost_bps)
            if t: trades.append(t); i+=t["bars"]+1; continue
        if bear and prev_not_bear:
            t=_exec_simple(d, i, "short", hold, at, rr, cost_bps)
            if t: trades.append(t); i+=t["bars"]+1; continue
        i+=1
    return trades

def run_donchian(d, cost_bps, period=20, hold=24, adx_min=25, rr=2.0):
    c=d["c"]; h=d["h"]; l=d["l"]
    ax=_adx(h,l,c); at=_atr(h,l,c); vs=_sma(d["v"],20)
    trades=[]; i=period+2
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [ax,at,vs]):
            i+=1; continue
        if ax[i]<adx_min or d["v"][i]<vs[i]: i+=1; continue
        hh=np.max(h[i-period:i]); ll=np.min(l[i-period:i])
        if c[i]>hh and c[i-1]<=np.max(h[i-period-1:i-1]):
            t=_exec_simple(d, i, "long", hold, at, rr, cost_bps)
            if t: trades.append(t); i+=t["bars"]+1; continue
        if c[i]<ll and c[i-1]>=np.min(l[i-period-1:i-1]):
            t=_exec_simple(d, i, "short", hold, at, rr, cost_bps)
            if t: trades.append(t); i+=t["bars"]+1; continue
        i+=1
    return trades


# ── Monte Carlo ───────────────────────────────────────
def mc_ruin(returns, n_sims=10000, n_per=200, ruin_pct=-30.0):
    if len(returns)<3: return 1.0, -9999
    ret=np.array(returns); rng=np.random.default_rng(42)
    ruin_ct=0; dds=[]
    thr=ruin_pct/100*10000
    for _ in range(n_sims):
        s=rng.choice(ret,n_per,replace=True)
        eq=np.cumsum(s); pk=np.maximum.accumulate(eq); dd=eq-pk
        md=np.min(dd); dds.append(md)
        if md<thr: ruin_ct+=1
    return ruin_ct/n_sims, float(np.median(dds))


# ── Stats helper ──────────────────────────────────────
def calc_stats(trades):
    if not trades: return None
    nets=[t["net"] for t in trades]; n=len(trades)
    wins=sum(1 for x in nets if x>0)
    gp=sum(x for x in nets if x>0); gl=abs(sum(x for x in nets if x<0))
    pf=gp/gl if gl>0 else (999 if gp>0 else 0)

    # Consecutive losses
    max_consec_loss=0; cur=0
    max_consec_loss_bps=0; cur_bps=0
    for x in nets:
        if x<=0: cur+=1; cur_bps+=x; max_consec_loss=max(max_consec_loss,cur); max_consec_loss_bps=min(max_consec_loss_bps,cur_bps)
        else: cur=0; cur_bps=0

    # Long/short split
    longs=[t for t in trades if t["side"]=="long"]
    shorts=[t for t in trades if t["side"]=="short"]
    long_wr=sum(1 for t in longs if t["net"]>0)/len(longs) if longs else 0
    short_wr=sum(1 for t in shorts if t["net"]>0)/len(shorts) if shorts else 0

    # Weekly buckets
    weekly=defaultdict(float)
    for t in trades:
        week = t["ts"] // (7*24*3600*1000)
        weekly[week] += t["net"]
    weekly_vals=list(weekly.values())
    win_weeks=sum(1 for w in weekly_vals if w>0)

    mc_ruin_pct, mc_dd = mc_ruin(nets)

    return {
        "n": n, "wr": wins/n, "pf": min(pf, 999),
        "tot": sum(nets), "avg": float(np.mean(nets)),
        "sharpe": float(np.mean(nets)/np.std(nets,ddof=1)) if n>1 and np.std(nets,ddof=1)>0 else 0,
        "max_consec_loss": max_consec_loss,
        "max_consec_loss_bps": max_consec_loss_bps,
        "n_long": len(longs), "n_short": len(shorts),
        "long_wr": long_wr, "short_wr": short_wr,
        "win_weeks": win_weeks, "total_weeks": len(weekly_vals),
        "mc_ruin": mc_ruin_pct, "mc_dd": mc_dd,
    }


# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════
def main():
    print("=" * 100)
    print("STRESS VERIFICATION — Final Pre-Live Check")
    print("=" * 100)

    # Define what we're testing
    strategies = [
        ("EMA_PartialTP_28", run_ema_partial, {"fast":9,"slow":21,"hold":24,"adx_min":28,"rr1":1.0,"rr2":2.5}),
        ("EMA_PartialTP_25", run_ema_partial, {"fast":9,"slow":21,"hold":24,"adx_min":25,"rr1":1.0,"rr2":3.0}),
        ("RSI_Trend", run_rsi_trend, {"hold":12,"adx_min":28,"rr":2.0}),
        ("EMA_Ribbon", run_ema_ribbon, {"hold":12,"adx_min":28,"rr":1.5}),
        ("Donchian", run_donchian, {"period":20,"hold":24,"adx_min":25,"rr":2.0}),
    ]

    cost_scenarios = [
        ("NORMAL", 2*BASE_FEE_BPS + 2*BASE_SLIP_BPS),  # 14 bps
        ("STRESS_2x", 2*(BASE_FEE_BPS*2) + 2*(BASE_SLIP_BPS*2)),  # 28 bps
        ("STRESS_3x", 2*(BASE_FEE_BPS*3) + 2*(BASE_SLIP_BPS*3)),  # 42 bps
    ]

    all_eligible = []

    for sname, sfn, sparams in strategies:
        print(f"\n\n{'='*100}")
        print(f"  STRATEGY: {sname}")
        print(f"  Params: {sparams}")
        print(f"{'='*100}")

        for sym in SYMBOLS:
            d1h = load(sym, "1h")
            if not d1h: continue
            n_bars = len(d1h["c"])
            midpoint = n_bars // 2

            print(f"\n{'─'*80}")
            print(f"  {sym} ({n_bars} bars)")
            print(f"{'─'*80}")

            for cost_name, cost_bps in cost_scenarios:
                trades = sfn(d1h, cost_bps, **sparams)
                if not trades:
                    print(f"  [{cost_name}] No trades")
                    continue
                s = calc_stats(trades)
                if not s: continue

                is_eligible = (s["pf"]>1.3 and s["wr"]>0.35 and s["n"]>=5
                              and s["mc_ruin"]<0.05 and s["max_consec_loss"]<=5)

                tag = "PASS" if is_eligible else "FAIL"
                pf_s = f"{s['pf']:.1f}" if s['pf']<100 else "inf"

                if cost_name == "NORMAL":
                    print(f"\n  [{cost_name} {cost_bps:.0f}bps] {tag}")
                    print(f"    Trades={s['n']} WR={s['wr']:.0%} PF={pf_s} Tot={s['tot']:.0f}bps Avg={s['avg']:.1f}bps Sharpe={s['sharpe']:.3f}")
                    print(f"    MC Ruin={s['mc_ruin']:.1%} MC DD={s['mc_dd']:.0f}bps")
                    print(f"    Max Consec Loss={s['max_consec_loss']} ({s['max_consec_loss_bps']:.0f}bps)")
                    print(f"    Long={s['n_long']}({s['long_wr']:.0%}) Short={s['n_short']}({s['short_wr']:.0%})")
                    print(f"    Win Weeks={s['win_weeks']}/{s['total_weeks']}")

                    # Trade-by-trade
                    print(f"\n    {'#':>2} {'Date':>12} {'Side':>5} {'Entry':>10} {'Exit':>10} {'Net':>7} {'SL':>5} {'Reason':>5} {'Bars':>4}")
                    for ti, t in enumerate(trades):
                        dt = datetime.fromtimestamp(t["ts"]/1000, tz=timezone.utc).strftime("%m/%d %H:%M")
                        print(f"    {ti+1:>2} {dt:>12} {t['side']:>5} {t['entry']:>10.2f} {t['exit']:>10.2f} {t['net']:>+7.1f} {t['sl_bps']:>5.0f} {t['reason']:>5} {t['bars']:>4}")

                    if is_eligible:
                        all_eligible.append((sname, sym, sparams, s))
                else:
                    print(f"  [{cost_name} {cost_bps:.0f}bps] {tag} | n={s['n']} PF={pf_s} Tot={s['tot']:.0f}bps MC={s['mc_ruin']:.1%}")

            # Walk-forward: split at midpoint
            if n_bars > 100:
                d_in = {k: v[:midpoint] for k,v in d1h.items()}
                d_out = {k: v[midpoint:] for k,v in d1h.items()}
                t_in = sfn(d_in, cost_scenarios[0][1], **sparams)
                t_out = sfn(d_out, cost_scenarios[0][1], **sparams)
                s_in = calc_stats(t_in) if t_in else None
                s_out = calc_stats(t_out) if t_out else None

                in_str = f"n={s_in['n']} PF={s_in['pf']:.1f} WR={s_in['wr']:.0%} Tot={s_in['tot']:.0f}" if s_in else "no trades"
                out_str = f"n={s_out['n']} PF={s_out['pf']:.1f} WR={s_out['wr']:.0%} Tot={s_out['tot']:.0f}" if s_out else "no trades"
                wf_pass = s_out and s_out["pf"] > 1.0 and s_out["n"] >= 2
                print(f"\n  Walk-Forward: {'PASS' if wf_pass else 'FAIL/INSUFF'}")
                print(f"    In-sample  (first {midpoint} bars): {in_str}")
                print(f"    Out-sample (last {n_bars-midpoint} bars): {out_str}")

    # ── Cross-correlation: simultaneous entries ──
    print(f"\n\n{'='*100}")
    print("  CROSS-SYMBOL ENTRY OVERLAP")
    print(f"{'='*100}")

    # Collect all entry timestamps per strategy
    for sname, sfn, sparams in strategies:
        entry_times = {}
        for sym in SYMBOLS:
            d1h = load(sym, "1h")
            if not d1h: continue
            trades = sfn(d1h, cost_scenarios[0][1], **sparams)
            entry_times[sym] = set(t["ts"] for t in trades)

        overlap_count = 0
        total_entries = sum(len(v) for v in entry_times.values())
        for sym1 in SYMBOLS:
            for sym2 in SYMBOLS:
                if sym1 >= sym2: continue
                if sym1 not in entry_times or sym2 not in entry_times: continue
                # Check within 3h window
                for t1 in entry_times[sym1]:
                    for t2 in entry_times[sym2]:
                        if abs(t1-t2) < 3*3600*1000:
                            overlap_count += 1
        print(f"  {sname}: {overlap_count} overlapping entries (within 3h) / {total_entries} total")

    # ── Final summary ──
    print(f"\n\n{'='*100}")
    print("  FINAL VERDICT")
    print(f"{'='*100}")

    seen = set()
    print(f"\n  {'Strategy':<20} {'Symbol':<10} {'N':>3} {'WR':>5} {'PF':>6} {'Tot':>7} {'MCR':>5} {'Consec':>6} {'Verdict'}")
    print(f"  {'─'*80}")
    for sname, sym, params, s in all_eligible:
        key = (sname, sym)
        if key in seen: continue
        seen.add(key)
        pf_s = f"{s['pf']:.1f}" if s['pf']<100 else "inf"
        verdict = "LIVE OK" if s["mc_ruin"]<0.05 and s["pf"]>1.3 and s["max_consec_loss"]<=4 else "CAUTION"
        print(f"  {sname:<20} {sym:<10} {s['n']:>3} {s['wr']:>4.0%} {pf_s:>6} {s['tot']:>7.0f} {s['mc_ruin']:>4.0%} {s['max_consec_loss']:>6} {verdict}")

    out = Path(__file__).resolve().parent.parent / "quant_runtime" / "output" / "signal_research"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "v5_stress_verify.json", "w") as f:
        json.dump([{"strategy": sn, "symbol": sy, "stats": {k: round(v,4) if isinstance(v,float) else v for k,v in st.items()}}
                   for sn,sy,_,st in all_eligible], f, indent=2)
    print(f"\n결과 저장: {out / 'v5_stress_verify.json'}")


if __name__ == "__main__":
    main()
