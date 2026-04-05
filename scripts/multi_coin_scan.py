#!/usr/bin/env python3
"""
Multi-Coin Full Scan
====================
1) Binance public API로 주요 코인 1h 데이터 374일 수집
2) 코인별 전체 전략 그리드서치 (374d, walk-forward, MC, stress)
3) 통과 코인+전략 조합 출력

대상: Binance 선물 거래량 상위 코인들
"""
from __future__ import annotations
import json, time, urllib.request, urllib.parse
from pathlib import Path
from collections import defaultdict
import numpy as np

HIST_DIR = Path(__file__).resolve().parent.parent / "quant_runtime" / "historical"
STOP_FLOOR_BPS = 45.0

# Binance 선물 거래량 상위 코인 (USDT pair)
ALL_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT",
    "BNBUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "DOTUSDT", "MATICUSDT", "NEARUSDT",
    "LTCUSDT", "UNIUSDT", "APTUSDT", "ARBUSDT",
    "OPUSDT", "SUIUSDT", "PEPEUSDT", "WIFUSDT",
]

# ══════════════════════════════════════════════════════
# DATA FETCH
# ══════════════════════════════════════════════════════
def fetch_binance(symbol, interval, end_ms, limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&endTime={end_ms}&limit={limit}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "multi-coin-scan/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                rows = json.loads(resp.read().decode("utf-8"))
            return [{"open_time":int(r[0]),"open_price":float(r[1]),"high_price":float(r[2]),
                     "low_price":float(r[3]),"close_price":float(r[4]),"base_volume":float(r[5]),
                     "quote_volume":float(r[7])} for r in rows]
        except Exception as e:
            if attempt < 2: time.sleep(1)
    return []

def ensure_data(symbol, tf="1h", target_bars=9000):
    sym_dir = HIST_DIR / symbol; sym_dir.mkdir(parents=True, exist_ok=True)
    path = sym_dir / f"{tf}.json"
    existing = []
    if path.exists():
        with open(path) as f: existing = json.load(f)
        if len(existing) >= target_bars * 0.9:
            return True  # already have enough

    bar_ms = 3600_000 if tf == "1h" else 14400_000
    now_ms = int(time.time() * 1000); end_ms = now_ms
    all_c = list(existing); seen = {c["open_time"] for c in all_c}

    while len(all_c) < target_bars:
        candles = fetch_binance(symbol, tf, end_ms)
        if not candles: break
        new = 0
        for c in candles:
            if c["open_time"] not in seen: seen.add(c["open_time"]); all_c.append(c); new += 1
        if new == 0: break
        end_ms = min(c["open_time"] for c in candles) - 1
        time.sleep(0.15)

    all_c.sort(key=lambda c: c["open_time"])
    # dedup
    final = []; s = set()
    for c in all_c:
        if c["open_time"] not in s: s.add(c["open_time"]); final.append(c)

    if final:
        with open(path, "w") as f: json.dump(final, f)
    return len(final) > 500

def load(sym, tf="1h"):
    p = HIST_DIR / sym / f"{tf}.json"
    if not p.exists(): return {}
    with open(p) as f: raw = json.load(f)
    if len(raw) < 200: return {}
    return {
        "t":np.array([c["open_time"] for c in raw],dtype=np.int64),
        "o":np.array([c["open_price"] for c in raw],dtype=np.float64),
        "h":np.array([c["high_price"] for c in raw],dtype=np.float64),
        "l":np.array([c["low_price"] for c in raw],dtype=np.float64),
        "c":np.array([c["close_price"] for c in raw],dtype=np.float64),
        "v":np.array([c["quote_volume"] for c in raw],dtype=np.float64),
    }

# ══════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════
def _ema(a,p):
    r=np.full_like(a,np.nan,dtype=np.float64)
    if len(a)<p:return r
    al=2.0/(p+1);r[p-1]=np.mean(a[:p])
    for i in range(p,len(a)):r[i]=al*a[i]+(1-al)*r[i-1]
    return r
def _sma(a,p):
    r=np.full_like(a,np.nan,dtype=np.float64)
    if len(a)<p:return r
    cs=np.cumsum(a);r[p-1:]=(cs[p-1:]-np.concatenate([[0],cs[:-p]]))/p
    return r
def _atr(h,l,c,p=14):
    r=np.full_like(c,np.nan)
    if len(c)<p+1:return r
    tr=np.maximum(h[1:]-l[1:],np.maximum(np.abs(h[1:]-c[:-1]),np.abs(l[1:]-c[:-1])))
    av=np.full(len(tr),np.nan);av[p-1]=np.mean(tr[:p])
    for i in range(p,len(tr)):av[i]=(av[i-1]*(p-1)+tr[i])/p
    r[1:]=av;return r
def _adx(h,l,c,p=14):
    r=np.full_like(c,np.nan);n=len(c)
    if n<2*p+1:return r
    up=h[1:]-h[:-1];down=l[:-1]-l[1:]
    pdm=np.where((up>down)&(up>0),up,0.0);mdm=np.where((down>up)&(down>0),down,0.0)
    tr=np.maximum(h[1:]-l[1:],np.maximum(np.abs(h[1:]-c[:-1]),np.abs(l[1:]-c[:-1])))
    st=np.full(len(tr),np.nan);sp=np.full(len(tr),np.nan);sm=np.full(len(tr),np.nan)
    st[p-1]=np.sum(tr[:p]);sp[p-1]=np.sum(pdm[:p]);sm[p-1]=np.sum(mdm[:p])
    for i in range(p,len(tr)):
        st[i]=st[i-1]-st[i-1]/p+tr[i];sp[i]=sp[i-1]-sp[i-1]/p+pdm[i];sm[i]=sm[i-1]-sm[i-1]/p+mdm[i]
    pdi=100*sp/np.where(st==0,1e-10,st);mdi=100*sm/np.where(st==0,1e-10,st)
    dx=100*np.abs(pdi-mdi)/np.where((pdi+mdi)==0,1e-10,pdi+mdi)
    av2=np.full(len(dx),np.nan);s2=2*p-1
    if s2<len(dx):
        av2[s2]=np.mean(dx[p-1:s2+1])
        for i in range(s2+1,len(dx)):av2[i]=(av2[i-1]*(p-1)+dx[i])/p
    r[1:]=av2;return r
def _rsi(c,p=14):
    r=np.full_like(c,np.nan)
    if len(c)<p+1:return r
    d=np.diff(c);g=np.where(d>0,d,0.0);lo=np.where(d<0,-d,0.0)
    ag=np.full(len(d),np.nan);al=np.full(len(d),np.nan)
    ag[p-1]=np.mean(g[:p]);al[p-1]=np.mean(lo[:p])
    for i in range(p,len(d)):ag[i]=(ag[i-1]*(p-1)+g[i])/p;al[i]=(al[i-1]*(p-1)+lo[i])/p
    rs=ag/np.where(al==0,1e-10,al);r[1:]=100-100/(1+rs)
    return r
def _macd(c,fast=12,slow=26,sig=9):
    ef=_ema(c,fast);es=_ema(c,slow);line=ef-es
    signal=_ema(np.where(np.isnan(line),0,line),sig)
    return line,signal
def _bb_width(c,p=20):
    mid=_sma(c,p);std=np.full_like(c,np.nan)
    for i in range(p-1,len(c)):std[i]=np.std(c[i-p+1:i+1],ddof=0)
    return 2*std/np.where(mid==0,1e-10,mid)*100

# ══════════════════════════════════════════════════════
# TRADE
# ══════════════════════════════════════════════════════
def _trade(d,i,side,hold,atr_v,sl_mult,rr,cost):
    c,h,l=d["c"],d["h"],d["l"]
    if i>=len(c)-2 or np.isnan(atr_v[i]) or atr_v[i]<=0:return None
    entry=c[i];sd=max(sl_mult*atr_v[i],entry*STOP_FLOOR_BPS/10000)
    tp=rr*sd
    if side=="long":sl_p=entry-sd;tp_p=entry+tp
    else:sl_p=entry+sd;tp_p=entry-tp
    ei=min(i+hold,len(c)-1);reason="TIME"
    for j in range(i+1,ei+1):
        if side=="long":
            if l[j]<=sl_p:ei=j;reason="SL";break
            if h[j]>=tp_p:ei=j;reason="TP";break
        else:
            if h[j]>=sl_p:ei=j;reason="SL";break
            if l[j]<=tp_p:ei=j;reason="TP";break
    ep=sl_p if reason=="SL" else (tp_p if reason=="TP" else c[ei])
    raw=(ep-entry)/entry*10000 if side=="long" else (entry-ep)/entry*10000
    return {"net":raw-cost,"bars":ei-i}

# ══════════════════════════════════════════════════════
# STRATEGIES
# ══════════════════════════════════════════════════════
def strat_ema(d,*,fast,slow,hold,adx_min,sl_mult,rr,cost,side_filter="both"):
    c=d["c"];ef=_ema(c,fast);es=_ema(c,slow);ax=_adx(d["h"],d["l"],c);at=_atr(d["h"],d["l"],c)
    trades=[];i=max(slow+1,55)
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [ef,es,ax,at]) or any(np.isnan(x[i-1]) for x in [ef,es]):i+=1;continue
        if ax[i]<adx_min:i+=1;continue
        up=ef[i-1]<=es[i-1] and ef[i]>es[i];dn=ef[i-1]>=es[i-1] and ef[i]<es[i]
        side=None
        if up and side_filter in("both","long"):side="long"
        elif dn and side_filter in("both","short"):side="short"
        if side:
            t=_trade(d,i,side,hold,at,sl_mult,rr,cost)
            if t:trades.append(t);i+=t["bars"]+1
            else:i+=1
        else:i+=1
    return trades

def strat_macd(d,*,hold,adx_min,sl_mult,rr,cost,side_filter="both"):
    c=d["c"];ml,ms=_macd(c);ax=_adx(d["h"],d["l"],c);at=_atr(d["h"],d["l"],c)
    trades=[];i=30
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [ml,ms,ax,at]) or any(np.isnan(x[i-1]) for x in [ml,ms]):i+=1;continue
        if ax[i]<adx_min:i+=1;continue
        up=ml[i-1]<=ms[i-1] and ml[i]>ms[i];dn=ml[i-1]>=ms[i-1] and ml[i]<ms[i]
        side=None
        if up and side_filter in("both","long"):side="long"
        elif dn and side_filter in("both","short"):side="short"
        if side:
            t=_trade(d,i,side,hold,at,sl_mult,rr,cost)
            if t:trades.append(t);i+=t["bars"]+1
            else:i+=1
        else:i+=1
    return trades

def strat_rsi50(d,*,hold,adx_min,sl_mult,rr,cost,side_filter="both"):
    c=d["c"];r=_rsi(c);ax=_adx(d["h"],d["l"],c);at=_atr(d["h"],d["l"],c);e50=_ema(c,50)
    trades=[];i=55
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [r,ax,at,e50]) or np.isnan(r[i-1]):i+=1;continue
        if ax[i]<adx_min:i+=1;continue
        side=None
        if r[i-1]<50 and r[i]>=50 and c[i]>e50[i] and side_filter in("both","long"):side="long"
        elif r[i-1]>50 and r[i]<=50 and c[i]<e50[i] and side_filter in("both","short"):side="short"
        if side:
            t=_trade(d,i,side,hold,at,sl_mult,rr,cost)
            if t:trades.append(t);i+=t["bars"]+1
            else:i+=1
        else:i+=1
    return trades

def strat_pullback(d,*,ema_p,hold,adx_min,sl_mult,rr,cost,rsi_entry=40):
    c=d["c"];e=_ema(c,ema_p);e50=_ema(c,50);r=_rsi(c);ax=_adx(d["h"],d["l"],c);at=_atr(d["h"],d["l"],c)
    trades=[];i=55
    while i<len(c)-hold:
        if any(np.isnan(x[i]) for x in [e,e50,r,ax,at]) or np.isnan(r[i-1]):i+=1;continue
        if ax[i]<adx_min:i+=1;continue
        side=None
        if c[i]>e50[i] and e[i]>e50[i] and r[i-1]<rsi_entry and r[i]>=rsi_entry and r[i]<60:side="long"
        elif c[i]<e50[i] and e[i]<e50[i] and r[i-1]>(100-rsi_entry) and r[i]<=(100-rsi_entry) and r[i]>40:side="short"
        if side:
            t=_trade(d,i,side,hold,at,sl_mult,rr,cost)
            if t:trades.append(t);i+=t["bars"]+1
            else:i+=1
        else:i+=1
    return trades

# ══════════════════════════════════════════════════════
# MC + STATS
# ══════════════════════════════════════════════════════
def mc_ruin(rets,n_sims=5000,n_per=200):
    if len(rets)<3:return 1.0
    ret=np.array(rets);rng=np.random.default_rng(42);rc=0
    for _ in range(n_sims):
        s=rng.choice(ret,n_per,replace=True);eq=np.cumsum(s);pk=np.maximum.accumulate(eq)
        if np.min(eq-pk)<-3000:rc+=1
    return rc/n_sims

def stats(trades):
    if not trades:return None
    nets=[t["net"] for t in trades];n=len(nets);wins=sum(1 for x in nets if x>0)
    gp=sum(x for x in nets if x>0);gl=abs(sum(x for x in nets if x<0))
    pf=gp/gl if gl>0 else(999 if gp>0 else 0)
    return{"n":n,"wr":wins/n,"pf":min(pf,999),"tot":sum(nets),"avg":float(np.mean(nets)),
           "sharpe":float(np.mean(nets)/np.std(nets,ddof=1)) if n>1 and np.std(nets,ddof=1)>0 else 0}

# ══════════════════════════════════════════════════════
# PARAM GRID
# ══════════════════════════════════════════════════════
def build_configs():
    configs = []
    # EMA Cross — wide sweep
    for fast,slow in [(8,21),(9,21),(10,21),(12,26),(20,50),(5,13)]:
        for hold in [12,18,24,36,48,72]:
            for adx_min in [20,25,28,30,35]:
                for sl_mult in [1.5,2.0,2.5,3.0]:
                    for rr in [1.5,2.0,2.5,3.0]:
                        for sf in ["both","long"]:
                            configs.append(("EMA",strat_ema,{"fast":fast,"slow":slow,"hold":hold,"adx_min":adx_min,"sl_mult":sl_mult,"rr":rr,"side_filter":sf}))
    # MACD
    for hold in [18,24,36,48]:
        for adx_min in [22,25,28,30]:
            for sl_mult in [2.0,2.5,3.0]:
                for rr in [2.0,2.5,3.0]:
                    for sf in ["both","long"]:
                        configs.append(("MACD",strat_macd,{"hold":hold,"adx_min":adx_min,"sl_mult":sl_mult,"rr":rr,"side_filter":sf}))
    # RSI 50
    for hold in [18,24,36]:
        for adx_min in [22,25,28,30]:
            for sl_mult in [2.0,2.5,3.0]:
                for rr in [2.0,2.5,3.0]:
                    for sf in ["both","long"]:
                        configs.append(("RSI50",strat_rsi50,{"hold":hold,"adx_min":adx_min,"sl_mult":sl_mult,"rr":rr,"side_filter":sf}))
    # Pullback
    for ema_p in [21,50]:
        for hold in [18,24,36]:
            for adx_min in [22,25,28]:
                for sl_mult in [2.0,2.5,3.0]:
                    for rr in [2.0,2.5,3.0]:
                        configs.append(("PULLBK",strat_pullback,{"ema_p":ema_p,"hold":hold,"adx_min":adx_min,"sl_mult":sl_mult,"rr":rr}))
    return configs

# ══════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════
def main():
    print("="*110)
    print("MULTI-COIN FULL SCAN — 20 coins × all strategies × 374d")
    print("="*110)

    # 1. Fetch data
    print("\n[1/3] Fetching 1h data...")
    available = []
    for sym in ALL_SYMBOLS:
        ok = ensure_data(sym, "1h", 9000)
        d = load(sym)
        if d:
            from datetime import datetime, timezone
            t0=datetime.fromtimestamp(d["t"][0]/1000,tz=timezone.utc)
            t1=datetime.fromtimestamp(d["t"][-1]/1000,tz=timezone.utc)
            days=(t1-t0).days
            print(f"  {sym}: {len(d['c'])} bars ({days}d)")
            if days >= 180:
                available.append(sym)
            else:
                print(f"    SKIP — only {days}d (<180d)")
        else:
            print(f"  {sym}: no data or <200 bars")

    print(f"\n  Available: {len(available)} coins")

    # 2. Grid search per coin
    print(f"\n[2/3] Grid search...")
    configs = build_configs()
    print(f"  {len(configs)} param combos per coin")

    all_eligible = []  # (sym, name, params, full_stats, out_stats, mc, stress_pf)

    for sym in available:
        d = load(sym)
        n = len(d["c"])
        split = int(n * 0.67)
        d_in = {k:v[:split] for k,v in d.items()}
        d_out = {k:v[split:] for k,v in d.items()}

        sym_pass = 0
        print(f"\n  {sym} ({n} bars, split={split})...", end="", flush=True)

        for name, fn, params in configs:
            trades = fn(d, cost=14.0, **params)
            s = stats(trades)
            if not s or s["n"]<20 or s["pf"]<=1.15 or s["wr"]<=0.35:
                continue

            # Walk-forward
            t_out = fn(d_out, cost=14.0, **params)
            s_out = stats(t_out)
            if not s_out or s_out["n"]<5 or s_out["pf"]<=1.0:
                continue

            # MC ruin
            mc = mc_ruin([t["net"] for t in trades])
            if mc > 0.05:
                continue

            # Stress
            t_stress = fn(d, cost=28.0, **params)
            s_stress = stats(t_stress)
            stress_pf = s_stress["pf"] if s_stress else 0

            sym_pass += 1
            all_eligible.append({
                "sym":sym,"name":name,
                "params":{k:v for k,v in params.items() if v not in (False,"both")},
                "full":s,"out":s_out,"mc":mc,"stress_pf":stress_pf,
                "stress_ok":bool(s_stress is not None and s_stress["pf"]>1.0),
            })

        print(f" {sym_pass} passed")

    # 3. Results
    print(f"\n\n{'='*110}")
    print(f"  RESULTS — {len(all_eligible)} coin×strategy combos passed all gates")
    print(f"  Gates: n>=20, PF>1.15, WR>35%, WF out PF>1.0 n>=5, MC ruin<5%")
    print(f"{'='*110}")

    # Group by coin
    by_coin = defaultdict(list)
    for e in all_eligible:
        by_coin[e["sym"]].append(e)

    # Summary per coin
    print(f"\n{'Coin':<12} {'Passed':>6} {'Best PF':>8} {'Best Strategy'}")
    print(f"{'─'*80}")
    for sym in available:
        entries = by_coin.get(sym, [])
        if entries:
            best = max(entries, key=lambda e: e["full"]["pf"])
            ps = ", ".join(f"{k}={v}" for k,v in best["params"].items())
            print(f"{sym:<12} {len(entries):>6} {best['full']['pf']:>8.2f} {best['name']} | {ps}")
        else:
            print(f"{sym:<12} {'0':>6} {'—':>8} no strategy survived 374d")

    # Top combos per coin (best 3)
    print(f"\n\n{'='*110}")
    print("  TOP 3 PER COIN")
    print(f"{'='*110}")
    for sym in available:
        entries = sorted(by_coin.get(sym, []), key=lambda e: e["full"]["pf"], reverse=True)[:3]
        if not entries:
            continue
        print(f"\n  {sym}:")
        for e in entries:
            s=e["full"];o=e["out"]
            ps=", ".join(f"{k}={v}" for k,v in e["params"].items())
            stag=" [stress OK]" if e["stress_ok"] else " [stress FAIL]"
            print(f"    {e['name']:<8} PF={s['pf']:.2f} n={s['n']} WR={s['wr']:.0%} Tot={s['tot']:.0f}bps OutPF={o['pf']:.2f} MC={e['mc']:.0%} StrPF={e['stress_pf']:.2f}{stag}")
            print(f"             {ps}")

    # Save
    out = Path(__file__).resolve().parent.parent / "quant_runtime" / "output" / "signal_research"
    out.mkdir(parents=True, exist_ok=True)

    save_data = {"coins_tested": len(available), "combos_passed": len(all_eligible), "per_coin": {}}
    for sym in available:
        entries = sorted(by_coin.get(sym, []), key=lambda e: e["full"]["pf"], reverse=True)
        save_data["per_coin"][sym] = [{
            "name":e["name"],"params":e["params"],
            "pf":round(e["full"]["pf"],4),"n":e["full"]["n"],"wr":round(e["full"]["wr"],4),
            "tot_bps":round(e["full"]["tot"],2),"out_pf":round(e["out"]["pf"],4),"out_n":e["out"]["n"],
            "mc":round(e["mc"],4),"stress_pf":round(e["stress_pf"],4),"stress_ok":bool(e["stress_ok"]),
        } for e in entries[:10]]

    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)): return int(obj)
            if isinstance(obj, (np.floating,)): return float(obj)
            if isinstance(obj, (np.bool_,)): return bool(obj)
            if isinstance(obj, np.ndarray): return obj.tolist()
            return super().default(obj)

    with open(out / "v8_multi_coin.json", "w") as f:
        json.dump(save_data, f, indent=2, cls=NpEncoder)
    print(f"\n결과 저장: {out / 'v8_multi_coin.json'}")


if __name__ == "__main__":
    main()
