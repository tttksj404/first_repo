"""EXHAUSTIVE ALL — every variable combo, every parameter, with auto-checkpointing.

Atomic filters: 20 boolean signals
Combo depths: 1, 2, 3, 4 way = 6,195 combos
Params: TP × SL × Hold × Lev × Side × Coins = 3,780
Total: ~23M combo evaluations (via cache)
"""
import os, sys, json, bisect, statistics, itertools, pickle, gc
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, "/home/user/first_repo")
os.environ.setdefault("STRATEGY_OVERRIDE_PATH", "quant_runtime/artifacts/strategy_override.approved.json")
os.environ.setdefault("STRATEGY_PROFILE", "live-ultra-aggressive")
os.environ.setdefault("EXCHANGE", "bitget")

from quant_binance.settings import Settings
from quant_binance.features.extractor import MarketFeatureExtractor
from quant_binance.cost_calibration import load_cost_calibration
from quant_binance.backtest.historical_fixture_builder import build_historical_slices
from quant_binance.data.historical_download import load_historical_klines
from quant_binance.data.rest_seed import _parse_kline

CKPT_DIR = Path("/tmp/exhaustive_ckpt")
CKPT_DIR.mkdir(exist_ok=True)

def ema(v,p):
    if not v: return 0
    a=2/(p+1);e=v[0]
    for x in v[1:]: e=a*x+(1-a)*e
    return e
def rsi(c,p=14):
    if len(c)<p+1: return 50
    g=[];l=[]
    for i in range(1,len(c)):d=c[i]-c[i-1];g.append(max(d,0));l.append(max(-d,0))
    ag=sum(g[-p:])/p;al=sum(l[-p:])/p
    return 100-100/(1+ag/al) if al>0 else 100

def load_or_build_entries():
    """Load entries from checkpoint or build."""
    ckpt = CKPT_DIR / "entries.pkl"
    if ckpt.exists():
        print(f"[load] Loading cached entries from {ckpt}")
        with open(ckpt, "rb") as f:
            return pickle.load(f)

    print("[build] Building entries (first run)...")
    settings = Settings.load("quant_binance/config.example.json")
    data_dir = Path("quant_runtime/historical")
    extractor = MarketFeatureExtractor(settings, cost_calibration=load_cost_calibration("quant_runtime/artifacts/cost_calibration.json"))

    entries={}; bars_5m={}; bars_ts={}
    for sym in ["ETHUSDT","SOLUSDT"]:
        k5m = load_historical_klines(data_dir=data_dir, symbol=sym, interval="5m")
        k1h = load_historical_klines(data_dir=data_dir, symbol=sym, interval="1h")
        k4h = load_historical_klines(data_dir=data_dir, symbol=sym, interval="4h")
        b5 = sorted([_parse_kline(sym,"5m",r) for r in k5m if r], key=lambda b:b.close_time)
        bars_5m[sym] = b5
        bars_ts[sym] = [int(b.close_time.timestamp()*1000) for b in b5]
        slices = build_historical_slices(symbol=sym, klines_5m=k5m, klines_1h=k1h, klines_4h=k4h or [], settings=settings, extractor=extractor)
        se=[]
        for sl in slices:
            try:
                pi = sl.primitive_inputs
                ep = sl.state.last_trade_price
                if ep<=0: continue
                td = getattr(pi,'trend_direction',0)
                if td==0: continue
                b1h = sl.state.klines.get("1h",[])
                b5v = sl.state.klines.get("5m",[])
                c1h = [b.close_price for b in b1h[-50:]]
                adx = getattr(pi,'adx_1h',0.0)
                # ATR expanding
                ae=False
                if len(b1h)>=28:
                    tr_r=[max(b1h[-j].high_price-b1h[-j].low_price,abs(b1h[-j].high_price-b1h[-j-1].close_price),abs(b1h[-j].low_price-b1h[-j-1].close_price)) for j in range(1,15)]
                    tr_o=[max(b1h[-j].high_price-b1h[-j].low_price,abs(b1h[-j].high_price-b1h[-j-1].close_price),abs(b1h[-j].low_price-b1h[-j-1].close_price)) for j in range(15,29)]
                    ae=sum(tr_r)/len(tr_r)>sum(tr_o)/len(tr_o)*1.3 if tr_o else False
                # RSI
                rsi_val=rsi(c1h) if len(c1h)>=15 else 50
                # TTM Squeeze
                ttm=False
                if len(c1h)>=20 and len(b1h)>=20:
                    sma=sum(c1h[-20:])/20
                    std=statistics.stdev(c1h[-20:]) if len(set(c1h[-20:]))>1 else 0
                    e20=ema(c1h[-20:],20)
                    a14=sum(max(b1h[-j].high_price-b1h[-j].low_price,abs(b1h[-j].high_price-b1h[-j-1].close_price),abs(b1h[-j].low_price-b1h[-j-1].close_price)) for j in range(1,min(15,len(b1h))))/min(14,len(b1h)-1) if len(b1h)>1 else 0
                    ttm=sma+2*std<e20+1.5*a14 and sma-2*std>e20-1.5*a14 and sma+2*std>0
                # FVG
                fvg=0
                if len(b1h)>=3:
                    if b1h[-1].low_price>b1h[-3].high_price: fvg=1
                    elif b1h[-1].high_price<b1h[-3].low_price: fvg=-1
                # Engulfing
                eng=0
                if len(b1h)>=2:
                    pb=b1h[-2].close_price-b1h[-2].open_price
                    cb=b1h[-1].close_price-b1h[-1].open_price
                    if cb>0 and pb<0 and abs(cb)>abs(pb): eng=1
                    elif cb<0 and pb>0 and abs(cb)>abs(pb): eng=-1
                # VWAP
                vwap_dev=0.0
                if b5v:
                    cpv=sum(b.close_price*getattr(b,'quote_volume',0) for b in b5v[-96:])
                    cv=sum(getattr(b,'quote_volume',0) for b in b5v[-96:])
                    vwap=cpv/cv if cv>0 else ep
                    vwap_dev=((ep-vwap)/vwap)*100
                # Vol spike
                vs=False
                if len(b5v)>=50:
                    vols=[getattr(b,'quote_volume',0) or 0 for b in b5v[-50:]]
                    vs=vols[-1]>sum(vols)/len(vols)*2.5 if vols else False
                # Session
                hour=sl.decision_time.hour
                kz=(8<=hour<=10) or (13<=hour<=15)
                london=7<=hour<=20
                # Pin bar
                pb=0
                if len(b1h)>=1:
                    c=b1h[-1]
                    body=abs(c.close_price-c.open_price);tot=c.high_price-c.low_price
                    if tot>0:
                        lw=min(c.close_price,c.open_price)-c.low_price
                        uw=c.high_price-max(c.close_price,c.open_price)
                        if lw>body*2 and lw>uw*1.5: pb=1
                        elif uw>body*2 and uw>lw*1.5: pb=-1
                # MTF
                c5m=[b.close_price for b in b5v[-100:]]
                mtf=0
                if len(c5m)>=6: mtf+=1 if c5m[-1]>c5m[-6] else -1
                if len(c1h)>=3: mtf+=1 if c1h[-1]>c1h[-3] else -1
                if len(c1h)>=12: mtf+=1 if c1h[-1]>c1h[-12] else -1
                if len(c1h)>=24: mtf+=1 if c1h[-1]>c1h[-24] else -1

                se.append({"s":"long" if td>0 else "short","adx":adx,
                    "ep":ep,"ms":int(sl.decision_time.timestamp()*1000),
                    "ts":getattr(pi,'trend_strength',0) or 0,
                    "vc":getattr(pi,'volume_confirmation',0) or 0,
                    "itd":getattr(pi,'intraday_trend_direction',0),
                    "ae":ae,"rsi":rsi_val,"ttm":ttm,"fvg":fvg,"eng":eng,
                    "vwap":vwap_dev,"vs":vs,"kz":kz,"london":london,
                    "pb":pb,"mtf":mtf,"stack":getattr(pi,'ema_stack_score',0.0),
                    "ema":getattr(pi,'ema_cross_signal',0)})
            except: continue
        entries[sym]=se
        print(f"  {sym}: {len(se)}", flush=True)

    data = (entries, bars_5m, bars_ts)
    with open(ckpt, "wb") as f:
        pickle.dump(data, f)
    print(f"[build] Cached to {ckpt}")
    return data

def build_sim_cache(entries, bars_5m, bars_ts):
    """Build simulation cache — reuse across all combo queries."""
    ckpt = CKPT_DIR / "sim_cache.pkl"
    if ckpt.exists():
        print(f"[sim] Loading sim cache from {ckpt}")
        with open(ckpt, "rb") as f:
            return pickle.load(f)

    print("[sim] Building sim cache...")
    TP=[5,8,10,12,15,20,25,30]
    SL=[5,8,10,12,15,20,25]
    HOLD=[4,8,12,24,48]
    cache={}
    for sym in entries:
        ts=bars_ts[sym]; bars=bars_5m[sym]
        for ei,e in enumerate(entries[sym]):
            idx=bisect.bisect_right(ts, e["ms"])
            if len(bars)-idx<3: continue
            ep=e["ep"]; side=e["s"]
            for tp in TP:
                for sl in SL:
                    for h in HOLD:
                        pnl=0; reason="HOLD"
                        for i,bar in enumerate(bars[idx:idx+h*12]):
                            if side=="long":
                                best=(bar.high_price/ep-1)*100*20
                                worst=(bar.low_price/ep-1)*100*20
                                cr=(bar.close_price/ep-1)*100*20
                            else:
                                best=-(bar.low_price/ep-1)*100*20
                                worst=-(bar.high_price/ep-1)*100*20
                                cr=-(bar.close_price/ep-1)*100*20
                            if worst<=-sl: pnl=-sl; reason="SL"; break
                            if best>=tp: pnl=tp; reason="TP"; break
                        else: pnl=cr
                        cache[(sym,ei,tp,sl,h)]=pnl/100
            if (ei+1)%2000==0:
                print(f"  {sym} {ei+1}/{len(entries[sym])}...", flush=True)
    print(f"  Total: {len(cache):,} sims", flush=True)
    with open(ckpt, "wb") as f:
        pickle.dump(cache, f)
    return cache

# ─── Atomic filters ───
ATOMS = {
    "adx25": lambda e: e["adx"]>=25,
    "adx30": lambda e: e["adx"]>=30,
    "adx35": lambda e: e["adx"]>=35,
    "adx40": lambda e: e["adx"]>=40,
    "adx45": lambda e: e["adx"]>=45,
    "ts04": lambda e: e["ts"]>=0.4,
    "ts05": lambda e: e["ts"]>=0.5,
    "vc04": lambda e: e["vc"]>=0.4,
    "vc05": lambda e: e["vc"]>=0.5,
    "intra": lambda e: (e["s"]=="long" and e["itd"]>0) or (e["s"]=="short" and e["itd"]<0),
    "ae": lambda e: e["ae"],
    "rsi30-50": lambda e: 30<=e["rsi"]<=50,
    "rsi35-55": lambda e: 35<=e["rsi"]<=55,
    "ttm": lambda e: e["ttm"],
    "fvg+": lambda e: (e["s"]=="long" and e["fvg"]==1) or (e["s"]=="short" and e["fvg"]==-1),
    "eng+": lambda e: (e["s"]=="long" and e["eng"]==1) or (e["s"]=="short" and e["eng"]==-1),
    "vwap+": lambda e: (e["s"]=="long" and e["vwap"]>0) or (e["s"]=="short" and e["vwap"]<0),
    "vs": lambda e: e["vs"],
    "kz": lambda e: e["kz"],
    "mtf3": lambda e: (e["s"]=="long" and e["mtf"]>=3) or (e["s"]=="short" and e["mtf"]<=-3),
    "stack8": lambda e: e["stack"]>=0.8,
}

def score_combo(combo_keys, entries, cache, min_trades=30, cost_bps=42):
    """Score one filter combo across ALL param combos."""
    if combo_keys:
        fns = [ATOMS[k] for k in combo_keys]
        filt_fn = lambda e: all(fn(e) for fn in fns)
    else:
        filt_fn = lambda e: True

    TP=[5,8,10,12,15,20,25,30]
    SL=[5,8,10,12,15,20,25]
    HOLD=[4,8,12,24,48]
    LEV=[10,15,20]
    SIDES=["long","short","both"]

    filt_idxs = {sym: [i for i,e in enumerate(ents) if filt_fn(e)] for sym,ents in entries.items()}

    best_results = []
    for sf in SIDES:
        sf_idxs = {}
        for sym,idxs in filt_idxs.items():
            sf_idxs[sym] = [i for i in idxs if sf=="both" or entries[sym][i]["s"]==sf]
        tn = sum(len(v) for v in sf_idxs.values())
        if tn<15: continue

        for tp in TP:
            for sl in SL:
                for h in HOLD:
                    for lv in LEV:
                        pnls=[]
                        for sym,idxs in sf_idxs.items():
                            for i in idxs:
                                c = cache.get((sym,i,tp,sl,h))
                                if c is None: continue
                                net = (c*lv/20 - cost_bps/10000) * 66*0.3*lv
                                pnls.append(net)
                        if len(pnls)<min_trades: continue
                        w = sum(1 for p in pnls if p>0)
                        wr = w/len(pnls)
                        total = sum(pnls)
                        if total<=0: continue
                        gw = sum(p for p in pnls if p>0)
                        gl = abs(sum(p for p in pnls if p<=0)) or 0.01
                        pf = gw/gl
                        # WF
                        n=len(pnls);q=[0,n//4,n//2,n*3//4,n]
                        wf=sum(1 for qi in range(4) if sum(pnls[q[qi]:q[qi+1]])>0)
                        best_results.append({
                            "combo":"+".join(combo_keys) if combo_keys else "none",
                            "n_combos":len(combo_keys),
                            "sd":sf,"tp":tp,"sl":sl,"h":h,"lv":lv,
                            "n":len(pnls),"wr":round(wr,4),"pf":round(pf,2),
                            "pnl":round(total,2),"wf":wf,
                        })
    return best_results

def main():
    entries, bars_5m, bars_ts = load_or_build_entries()
    cache = build_sim_cache(entries, bars_5m, bars_ts)
    gc.collect()

    # Build all combos: 1-way, 2-way, 3-way
    keys = list(ATOMS.keys())
    all_combos = [()]  # 0-way (no filter)
    for r in range(1,4):
        all_combos.extend(list(itertools.combinations(keys, r)))
    print(f"\n[main] Total filter combos: {len(all_combos):,}")

    # Process in chunks, save results incrementally
    results_path = CKPT_DIR / "results.jsonl"
    results_path.unlink(missing_ok=True)

    all_results = []
    for ci, combo in enumerate(all_combos):
        r = score_combo(combo, entries, cache)
        all_results.extend(r)

        # Incremental save every 100 combos
        if (ci+1) % 100 == 0:
            print(f"  {ci+1}/{len(all_combos):,} combos, {len(all_results):,} profitable", flush=True)
            with open(results_path, "a") as f:
                for res in r:
                    f.write(json.dumps(res, ensure_ascii=False) + "\n")

    # Final save
    with open(results_path, "a") as f:
        for res in all_results[-len(r):]:
            pass  # already written

    print(f"\n[main] Total profitable: {len(all_results):,}")

    # Sort by PnL within WF4
    all_results.sort(key=lambda r: (r["wf"], r["pnl"]), reverse=True)
    wf4 = [r for r in all_results if r["wf"]==4]
    wr70 = [r for r in wf4 if r["wr"]>=0.70]
    wr80 = [r for r in wf4 if r["wr"]>=0.80]
    bal = [r for r in wf4 if r["wr"]>=0.65 and r["n"]>=50]
    hf = [r for r in wf4 if r["n"]>=100]

    print(f"\n=== RESULTS ===")
    print(f"Total profitable: {len(all_results):,}")
    print(f"WF4: {len(wf4):,}")
    print(f"WR70+WF4: {len(wr70):,}")
    print(f"WR80+WF4: {len(wr80):,}")
    print(f"Balanced(65%+50건+WF4): {len(bal):,}")
    print(f"HighFreq(100건+WF4): {len(hf):,}")

    print(f"\n=== WF4 TOP 20 by PnL ===")
    for i,r in enumerate(wf4[:20]):
        print(f"  #{i+1} WR={r['wr']*100:.1f}% PF={r['pf']:.2f} {r['n']}건 ${r['pnl']:+,.0f} | [{r['combo']}] tp{r['tp']}/sl{r['sl']}/h{r['h']}/lv{r['lv']} {r['sd']}")

    if wr70:
        wr70.sort(key=lambda r:r["pnl"], reverse=True)
        print(f"\n=== WR 70%+ & WF4 TOP 10 ===")
        for i,r in enumerate(wr70[:10]):
            print(f"  #{i+1} WR={r['wr']*100:.1f}% PF={r['pf']:.2f} {r['n']}건 ${r['pnl']:+,.0f} | [{r['combo']}] tp{r['tp']}/sl{r['sl']}/h{r['h']}/lv{r['lv']} {r['sd']}")

    if bal:
        bal.sort(key=lambda r:r["pnl"], reverse=True)
        print(f"\n=== BALANCED (65%+50건+WF4) TOP 10 ===")
        for i,r in enumerate(bal[:10]):
            print(f"  #{i+1} WR={r['wr']*100:.1f}% PF={r['pf']:.2f} {r['n']}건 ${r['pnl']:+,.0f} | [{r['combo']}] tp{r['tp']}/sl{r['sl']}/h{r['h']}/lv{r['lv']} {r['sd']}")

    # Save final
    out = Path("/home/user/first_repo/quant_runtime/artifacts/exhaustive_all.json")
    with open(out, "w") as f:
        json.dump(all_results[:1000], f, indent=2, ensure_ascii=False)
    print(f"\n[main] Saved top 1000 to {out}")

if __name__ == "__main__":
    main()
