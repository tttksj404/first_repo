"""3-year exhaustive backtest — 1h decision + 1h bar exit tracking.

Fast: iterates 26K 1h bars (not 314K 5m), pre-computes all indicators once.
Tests 41K+ variable combos with walk-forward + cost stress.
"""
from __future__ import annotations
import argparse,json,math,os,statistics,sys,time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

def ema(v,p):
    if len(v)<p: return sum(v)/max(len(v),1)
    k=2/(p+1); e=sum(v[:p])/p
    for x in v[p:]: e=x*k+e*(1-k)
    return e

def atr_val(h,l,c,p=14):
    if len(h)<2: return 0
    trs=[max(h[-i]-l[-i],abs(h[-i]-c[-i-1]),abs(l[-i]-c[-i-1])) for i in range(1,min(len(h),p+1))]
    return sum(trs)/max(len(trs),1)

def adx_val(h,l,c,p=14):
    if len(h)<p+2: return 0
    pdm=[];mdm=[];trs=[]
    for i in range(1,min(len(h),p+2)):
        hd=h[-i]-h[-i-1];ld=l[-i-1]-l[-i]
        pdm.append(max(hd,0) if hd>ld else 0);mdm.append(max(ld,0) if ld>hd else 0)
        trs.append(max(h[-i]-l[-i],abs(h[-i]-c[-i-1]),abs(l[-i]-c[-i-1])))
    a=sum(trs[:p])/p
    if a<=0: return 0
    pdi=(sum(pdm[:p])/p)/a*100;mdi=(sum(mdm[:p])/p)/a*100
    return abs(pdi-mdi)/max(pdi+mdi,0.01)*100

def rsi_val(c,p=14):
    if len(c)<p+1: return 50
    g=[max(c[i]-c[i-1],0) for i in range(-p,0)];l=[max(c[i-1]-c[i],0) for i in range(-p,0)]
    ag=sum(g)/p;al=sum(l)/p
    return 100-100/(1+ag/al) if al>0 else 100

def ttm_sq(c,h,l,p=20):
    if len(c)<p: return False
    s=sum(c[-p:])/p;sd=statistics.stdev(c[-p:]) if len(set(c[-p:]))>1 else 0;a=atr_val(h,l,c,14)
    return (s+2*sd)<(s+1.5*a) and (s-2*sd)>(s-1.5*a) and (s+2*sd)>0

@dataclass
class T:
    sym:str="";side:str="";ei:int=0;ep:float=0;xi:int=0;xp:float=0;xr:str=""
    lev:int=12;not_:float=0;sp:float=0;pk:float=0;pnl:float=0

@dataclass
class C:
    ttm:bool=True;adx_min:float=0;rsi_lo:float=0;rsi_hi:float=100
    emx:bool=False;ts:float=0;vs:float=0;iday:bool=False;fund:bool=False
    hour:str="";side:str="both"
    tp_r:float=1.9;sl_r:float=1.0;be_r:float=1.15;stale:int=8;maxh:float=24
    trail_r:float=99;trail_l:float=0.5;lev:int=12
    @property
    def label(self):
        p=[]
        if self.ttm:p.append("ttm")
        if self.adx_min>0:p.append(f"adx{self.adx_min:.0f}")
        if self.rsi_lo>0 or self.rsi_hi<100:p.append(f"rsi{self.rsi_lo:.0f}-{self.rsi_hi:.0f}")
        if self.emx:p.append("emx")
        if self.ts>0:p.append(f"ts{self.ts:.0f}")
        if self.vs>0:p.append(f"vs{self.vs:.1f}")
        if self.iday:p.append("iday")
        if self.fund:p.append("fund")
        if self.hour:p.append(f"h_{self.hour}")
        if self.side!="both":p.append(self.side[0])
        e=f"tp{self.tp_r:.1f}_sl{self.sl_r:.1f}_h{self.maxh:.0f}_lv{self.lev}"
        if self.trail_r<50:e+=f"_tr{self.trail_r:.0f}"
        return ("_".join(p) or "base")+"|"+e

def run(h,l,c,v,e20s,e50s,e200s,adxs,rsis,squeezes,e200_4h,e50_4h,funding,cfg,eq,cost,sym):
    trades=[];pos=None;cd=0;dl=0.0;dd="";cl=0;r1=eq*0.0075
    atr_h=[];n=len(c)
    for i in range(200,n):
        dt_=datetime.fromtimestamp(h[0] if i==0 else 0,tz=timezone.utc) # placeholder
        d=str(i//24)  # approximate day
        if d!=dd:dl=0;dd=d
        # Position exit
        if pos is not None:
            hi_=h[i];lo_=l[i];cl_=c[i];ep=pos.ep;lv=pos.lev;sp=pos.sp
            if pos.side=="long":best=(hi_/ep-1)*100*lv;worst=(lo_/ep-1)*100*lv;cur=(cl_/ep-1)*100*lv
            else:best=-(lo_/ep-1)*100*lv;worst=-(hi_/ep-1)*100*lv;cur=-(cl_/ep-1)*100*lv
            pos.pk=max(pos.pk,best)
            sl_r=-sp*100*lv*cfg.sl_r;tp_r=sp*100*lv*cfg.tp_r
            if pos.pk>=sp*100*lv*cfg.be_r:sl_r=sp*100*lv*0.1
            if cfg.trail_r<50 and pos.pk>=sp*100*lv*cfg.trail_r:
                locked=pos.pk*cfg.trail_l
                if cur<=locked and locked>0:
                    pos.xi=i;pos.xp=cl_;pos.xr="TRAIL";_f(pos,cost);trades.append(pos)
                    dl+=pos.pnl;cl=cl+1 if pos.pnl<=0 else 0;cd=i+1;pos=None;continue
            if worst<=sl_r:
                pos.xp=ep*(1+sl_r/100/lv) if pos.side=="long" else ep*(1-sl_r/100/lv)
                pos.xi=i;pos.xr="SL";_f(pos,cost);trades.append(pos)
                dl+=pos.pnl;cl=cl+1 if pos.pnl<=0 else 0;cd=i+3;pos=None;continue
            if best>=tp_r:
                pos.xp=ep*(1+tp_r/100/lv) if pos.side=="long" else ep*(1-tp_r/100/lv)
                pos.xi=i;pos.xr="TP";_f(pos,cost);trades.append(pos);dl+=pos.pnl;cl=0;cd=i+1;pos=None;continue
            bh=i-pos.ei
            mr=pos.pk/(sp*100*lv) if sp>0 else 0;cr=cur/(sp*100*lv) if sp>0 else 0
            if bh>=cfg.stale and mr<0.5 and cr<0.25:
                pos.xi=i;pos.xp=cl_;pos.xr="STALE";_f(pos,cost);trades.append(pos)
                dl+=pos.pnl;cl=cl+1 if pos.pnl<=0 else 0;cd=i+1;pos=None;continue
            if bh>=cfg.maxh:
                pos.xi=i;pos.xp=cl_;pos.xr="TIME";_f(pos,cost);trades.append(pos);dl+=pos.pnl;pos=None;continue
            continue
        # Entry
        if i<cd:continue
        if dl<=-2*r1:continue
        if cl>=3:cl=0;cd=i+6;continue
        # Filters
        if i>=len(adxs) or i>=len(rsis) or i>=len(squeezes):continue
        if cfg.adx_min>0 and adxs[i]<cfg.adx_min:continue
        if rsis[i]<cfg.rsi_lo or rsis[i]>cfg.rsi_hi:continue
        # ATR regime
        at=atr_val(h[:i+1],l[:i+1],c[:i+1],14);ap=at/c[i] if c[i]>0 else 0
        atr_h.append(ap)
        if len(atr_h)>500:atr_h=atr_h[-500:]
        if len(atr_h)>=50:
            rk=sum(1 for a in atr_h if a<=ap)/len(atr_h)
            if rk<0.3 or rk>0.85:continue
        # 4h regime
        i4=min(i//4,len(e200_4h)-1)
        if i4<5:continue
        long_ok=c[i]>e200_4h[i4] and e20s[i]>e50s[i]>e200s[i]
        short_ok=c[i]<e200_4h[i4] and e20s[i]<e50s[i]<e200s[i]
        if not long_ok and not short_ok:continue
        # TTM
        if cfg.ttm:
            if i<6:continue
            sq_count=sum(squeezes[i-j] for j in range(1,min(7,i+1)))
            released=not squeezes[i]
            if sq_count<3 or not released:continue
        # Donchian
        dc_h=max(h[max(0,i-20):i]);dc_l=min(l[max(0,i-20):i])
        sd=""
        if long_ok and c[i]>dc_h+0.1*at:sd="long"
        elif short_ok and c[i]<dc_l-0.1*at:sd="short"
        if not sd:continue
        if cfg.side!="both" and sd!=cfg.side:continue
        # EMA cross
        if cfg.emx:
            e8=ema(c[max(0,i-30):i+1],8);e21=ema(c[max(0,i-30):i+1],21)
            if sd=="long" and e8<=e21:continue
            if sd=="short" and e8>=e21:continue
        # Trend strength
        if cfg.ts>0:
            if i<10:continue
            sl=abs(e20s[i]-e20s[max(0,i-5)])/max(e20s[i],1)
            if sl<cfg.ts/10000:continue
        # Volume
        if cfg.vs>0:
            vm=sorted(v[max(0,i-20):i])[min(len(v[max(0,i-20):i])//2,9)] if i>20 else 1
            if v[i]<cfg.vs*vm:continue
        # Intraday
        if cfg.iday:
            if i<5:continue
            ef=ema(c[max(0,i-10):i+1],3);es=ema(c[max(0,i-10):i+1],10)
            if sd=="long" and ef<=es:continue
            if sd=="short" and ef>=es:continue
        # Funding
        if cfg.fund and funding:
            nearest=max((t for t in funding if t<=i*3600000),default=0)  # approx
            if nearest:
                fv=funding[nearest]
                if sd=="long" and fv>0.0003:continue
                if sd=="short" and fv<-0.0003:continue
        # Hour filter
        if cfg.hour:
            hr=(i%24)  # approximate
            if cfg.hour=="kill" and hr not in (2,3,8,9,14,15):continue
        # Enter
        sp=max(0.0085,2.0*at/c[i])
        not_=r1/sp*(0.5 if cl>=2 else 1.0)
        pos=T(sym=sym,side=sd,ei=i,ep=c[i],lev=cfg.lev,not_=not_,sp=sp)
    if pos:
        pos.xi=n-1;pos.xp=c[-1];pos.xr="END";_f(pos,cost);trades.append(pos)
    return trades

def _f(t,cost):
    if not t.xp or t.ep<=0:return
    r=(t.xp/t.ep-1) if t.side=="long" else -(t.xp/t.ep-1)
    t.pnl=t.not_*r-t.not_*cost/10000

def wf(ts,n=4):
    if len(ts)<n*3:return {"v":False,"f":[],"p":0}
    s=sorted(ts,key=lambda t:t.ei);fs=len(s)//n;folds=[]
    for i in range(n):
        f=s[i*fs:(i+1)*fs if i<n-1 else len(s)]
        pnl=sum(t.pnl for t in f);wr=sum(1 for t in f if t.pnl>0)/max(len(f),1)
        folds.append({"q":i+1,"n":len(f),"pnl":round(pnl,2),"wr":round(wr,4)})
    pc=sum(1 for f in folds if f["pnl"]>0)
    return {"v":pc>=3,"f":folds,"p":pc}

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--symbols",default="ETHUSDT,SOLUSDT")
    parser.add_argument("--equity-usd",type=float,default=75)
    parser.add_argument("--top-n",type=int,default=30)
    args=parser.parse_args(argv)
    symbols=[s.strip() for s in args.symbols.split(",")]
    dd=Path("quant_runtime/historical")

    # Load and precompute per-symbol
    sym_data={}
    for sym in symbols:
        b1=json.load(open(dd/sym/"1h.json"))
        b4=json.load(open(dd/sym/"4h.json"))
        fr_p=dd/sym/"funding.json"
        fr=json.load(open(fr_p)) if fr_p.exists() else []
        c=[b["close_price"] for b in b1];h=[b["high_price"] for b in b1]
        l=[b["low_price"] for b in b1];v=[b.get("base_volume",b.get("quote_volume",0)) for b in b1]
        n=len(c)
        print(f"  {sym}: {n:,} 1h bars, precomputing indicators...",flush=True)
        e20=[ema(c[:i+1],20) for i in range(n)]
        e50=[ema(c[:i+1],50) for i in range(n)]
        e200=[ema(c[:i+1],200) if i>=200 else ema(c[:i+1],max(i+1,1)) for i in range(n)]
        adxs=[adx_val(h[:i+1],l[:i+1],c[:i+1],14) if i>=16 else 0 for i in range(n)]
        rsis=[rsi_val(c[:i+1],14) if i>=15 else 50 for i in range(n)]
        squeezes=[ttm_sq(c[max(0,i-20):i+1],h[max(0,i-20):i+1],l[max(0,i-20):i+1]) for i in range(n)]
        # 4h EMA
        c4=[b["close_price"] for b in b4]
        e200_4h=[ema(c4[:i+1],200) if i>=200 else ema(c4[:i+1],max(i+1,1)) for i in range(len(c4))]
        e50_4h=[ema(c4[:i+1],50) if i>=50 else ema(c4[:i+1],max(i+1,1)) for i in range(len(c4))]
        fr_map={int(f.get("funding_time",0)):float(f.get("funding_rate",0)) for f in fr}
        print(f"  {sym}: indicators ready",flush=True)
        sym_data[sym]=(h,l,c,v,e20,e50,e200,adxs,rsis,squeezes,e200_4h,e50_4h,fr_map)

    # Build configs
    configs=[]
    for ttm in [True,False]:
     for adx_ in [0,18,25]:
      for rsi_r in [(0,100),(40,70),(50,68)]:
       for emx in [False,True]:
        for ts in [0,1]:
         for vs in [0,1.15]:
          for iday in [False,True]:
           for fund in [False,True]:
            for hour in ["","kill"]:
             for side in ["both","long","short"]:
              for tp in [1.5,1.9,2.5]:
               for sl in [1.0,1.5]:
                for maxh in [12,24,48]:
                 for lev in [12,15]:
                  configs.append(C(ttm=ttm,adx_min=adx_,rsi_lo=rsi_r[0],rsi_hi=rsi_r[1],
                    emx=emx,ts=ts,vs=vs,iday=iday,fund=fund,hour=hour,side=side,
                    tp_r=tp,sl_r=sl,maxh=maxh,lev=lev))

    print(f"\n[3Y] {len(configs):,} configs x {len(sym_data)} symbols @ 24bps",flush=True)

    results=[];t0=time.time()
    for ci,cfg in enumerate(configs):
        all_t=[]
        for sym,(h,l,c,v,e20,e50,e200,adxs,rsis,sq,e200_4h,e50_4h,fr) in sym_data.items():
            ts_=run(h,l,c,v,e20,e50,e200,adxs,rsis,sq,e200_4h,e50_4h,fr,cfg,args.equity_usd,24.0,sym)
            all_t.extend(ts_)
        if not all_t:continue
        n_=len(all_t);w=sum(1 for t in all_t if t.pnl>0)
        pnl=sum(t.pnl for t in all_t)
        gp=sum(t.pnl for t in all_t if t.pnl>0);gl=abs(sum(t.pnl for t in all_t if t.pnl<=0))
        pf=gp/max(gl,0.01);wr=w/max(n_,1)
        w_=wf(all_t)
        results.append({"c":cfg,"t":all_t,"n":n_,"wr":wr,"pnl":pnl,"pf":pf,"wf":w_,"lb":cfg.label})
        if (ci+1)%5000==0:
            el=time.time()-t0;eta=el/(ci+1)*(len(configs)-ci-1)
            bp=max((r["pnl"] for r in results),default=0)
            pr=sum(1 for r in results if r["pnl"]>0)
            print(f"  [{ci+1:,}/{len(configs):,}] {pr} profitable, best=${bp:.0f}, ETA {eta/60:.0f}m",flush=True)

    el=time.time()-t0
    print(f"\n  Done in {el/60:.1f}m. {len(results)} combos with trades.",flush=True)

    results.sort(key=lambda r:(r["wf"]["v"],r["pnl"]),reverse=True)

    print(f"\n{'='*130}",flush=True)
    print(f"{'3-YEAR EXHAUSTIVE (1h bars, 24bps, WF, circuit breaker)':^130}",flush=True)
    print(f"{'='*130}",flush=True)
    print(f"{'#':>3} {'WF':>2} {'Config':>55} {'N':>5} {'WR%':>5} {'PnL$':>8} {'PF':>5} {'Q1':>6} {'Q2':>6} {'Q3':>6} {'Q4':>6}",flush=True)
    print("-"*130,flush=True)
    for i,r in enumerate(results[:args.top_n]):
        fs=r["wf"].get("f",[])
        qs=[f"${f['pnl']:+.0f}" for f in fs]+["?"]*4
        print(f"{i+1:>3} {'V' if r['wf']['v'] else ' ':>2} {r['lb'][:55]:>55} {r['n']:>5} {r['wr']*100:>5.1f} {r['pnl']:>8.1f} {r['pf']:>5.2f} {qs[0]:>6} {qs[1]:>6} {qs[2]:>6} {qs[3]:>6}",flush=True)

    # Cost stress on top 10
    if results:
        print(f"\nCOST STRESS (top 10):",flush=True)
        for i,r in enumerate(results[:10]):
            line=f"  {i+1}. "
            for cost in [16,24,42]:
                at=[]
                for sym,(h,l,c,v,e20,e50,e200,adxs,rsis,sq,e200_4h,e50_4h,fr) in sym_data.items():
                    at.extend(run(h,l,c,v,e20,e50,e200,adxs,rsis,sq,e200_4h,e50_4h,fr,r["c"],args.equity_usd,float(cost),sym))
                p=sum(t.pnl for t in at);w=sum(1 for t in at if t.pnl>0)/max(len(at),1)
                line+=f" {cost}bps:${p:+.0f}/WR{w*100:.0f}%"
            print(line,flush=True)

    # Detailed top
    if results:
        b=results[0]
        print(f"\n{'='*80}",flush=True)
        print(f"TOP: {b['lb']}",flush=True)
        print(f"N={b['n']} WR={b['wr']*100:.1f}% PnL=${b['pnl']:.2f} PF={b['pf']:.2f}",flush=True)
        print(f"WF: {'VALID' if b['wf']['v'] else 'FAIL'} ({b['wf']['p']}/4)",flush=True)
        for f in b["wf"].get("f",[]):print(f"  Q{f['q']}: {f['n']}t WR={f['wr']*100:.1f}% ${f['pnl']:+.2f}",flush=True)
        rs=defaultdict(list)
        for t in b["t"]:rs[t.xr].append(t)
        for er,ts in sorted(rs.items(),key=lambda x:-len(x[1])):
            print(f"  {er:8s}: {len(ts):4d}t avg=${sum(t.pnl for t in ts)/len(ts):+.2f}",flush=True)

    out=Path("quant_runtime/output/exhaustive_3y_results.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    sv=[{"lb":r["lb"],"n":r["n"],"wr":round(r["wr"],4),"pnl":round(r["pnl"],2),
         "pf":round(r["pf"],2),"wf_v":r["wf"]["v"],"wf_p":r["wf"]["p"]}
        for r in results[:200]]
    out.write_text(json.dumps(sv,indent=2))
    print(f"\nSaved to {out}",flush=True)
    return 0

if __name__=="__main__":sys.exit(main())
