"""5-minute bar backtest with validated coin profiles + alpha strategies.

Uses 103K 5m bars per symbol, real Bybit OI data, validated coin profiles as baseline.
Ablation: baseline → +OI_filter → +SMC_boost → +VWAP_gate → +alpha_entries
"""
from __future__ import annotations
import json,math,random,statistics,sys,time
from collections import defaultdict
from dataclasses import dataclass,field
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))

# ── Indicators (5m optimized) ──
def ema(v,p):
    if not v: return 0
    if len(v)<p: return sum(v)/len(v)
    k=2/(p+1);e=sum(v[:p])/p
    for x in v[p:]:e=x*k+e*(1-k)
    return e

def atr_bars(h,l,c,p=14):
    if len(h)<2:return 0
    trs=[]
    for i in range(1,min(len(h),p+1)):
        trs.append(max(h[-i]-l[-i],abs(h[-i]-c[-i-1]),abs(l[-i]-c[-i-1])))
    return sum(trs)/max(len(trs),1)

def adx_bars(h,l,c,p=14):
    if len(h)<p+2:return 0
    pdm=[];mdm=[];trs=[]
    for i in range(1,min(len(h),p+2)):
        hd=h[-i]-h[-i-1];ld=l[-i-1]-l[-i]
        pdm.append(max(hd,0) if hd>ld else 0);mdm.append(max(ld,0) if ld>hd else 0)
        trs.append(max(h[-i]-l[-i],abs(h[-i]-c[-i-1]),abs(l[-i]-c[-i-1])))
    a=sum(trs[:p])/p
    if a<=0:return 0
    pdi=(sum(pdm[:p])/p)/a*100;mdi=(sum(mdm[:p])/p)/a*100
    return abs(pdi-mdi)/max(pdi+mdi,0.01)*100

def rsi_bars(c,p=14):
    if len(c)<p+1:return 50
    g=[max(c[i]-c[i-1],0) for i in range(-p,0)];l_=[max(c[i-1]-c[i],0) for i in range(-p,0)]
    ag=sum(g)/p;al=sum(l_)/p
    return 100-100/(1+ag/al) if al>0 else 100

def vwap_5m(h,l,c,v,n=288):
    """VWAP over last n 5m bars (~24h)."""
    s=max(0,len(c)-n);cpv=0;cv=0
    for i in range(s,len(c)):
        tp=(h[i]+l[i]+c[i])/3;cpv+=tp*v[i];cv+=v[i]
    return cpv/max(cv,1e-12)

def vwap_z_5m(h,l,c,v,i,n=288):
    s=max(0,i-n+1)
    vw=vwap_5m(h[s:i+1],l[s:i+1],c[s:i+1],v[s:i+1],n)
    # Fast z-score: sample every 6th bar instead of every bar
    devs=[]
    for j in range(max(s+12,i-96),i+1,6):
        ss=max(0,j-n+1)
        vj=vwap_5m(h[ss:j+1],l[ss:j+1],c[ss:j+1],v[ss:j+1],n)
        devs.append(c[j]-vj)
    if len(devs)<2:return 0.0,vw
    d=c[i]-vw;m=sum(devs)/len(devs);sd=statistics.pstdev(devs)
    z=(d-m)/sd if sd>1e-12 else 0
    return max(-4,min(4,z)),vw

def oi_div_5m(oi,c,i,lb=288):
    """OI divergence at 5m resolution (lb=288 = 24h)."""
    if i<lb or len(oi)<=i:return 0.0
    prices=c[i-lb:i+1];ois=oi[max(0,i-lb):i+1]
    if len(ois)<lb:return 0.0
    cp=prices[-1];ph=max(prices[:-1]);pl=min(prices[:-1])
    on=ois[-1];oa=sum(ois[:-1])/max(len(ois)-1,1)
    od=(on-oa)/max(abs(oa),1e-12)
    nh=cp>ph;nl=cp<pl
    if nh and od<-0.02:return -0.6
    if nh and od>0.03:return 0.6
    if nl and od<-0.02:return 0.5
    if nl and od>0.03:return -0.5
    return max(-0.3,min(0.3,od*3))

def fvg_5m(h,l,i,lb=60):
    """FVG score on 5m bars."""
    if i<3:return 0.0
    sc=0.0
    for j in range(max(2,i-lb),i+1):
        if l[j]>h[j-2]:
            gp=(l[j]-h[j-2])/h[j-2]*100
            if 0.02<=gp<=0.3:
                if h[j-2]<=h[i] and l[i]<=l[j]:
                    age=i-j;sc=max(sc,0.3+0.7*max(0,1-age/40))
        if h[j]<l[j-2]:
            gp=(l[j-2]-h[j])/l[j-2]*100
            if 0.02<=gp<=0.3:
                if l[j-2]>=l[i] and h[i]>=h[j]:
                    age=i-j;sc=max(sc,0.3+0.7*max(0,1-age/40))
    return sc

def ob_5m(h,l,c,o,at,i,lb=40):
    """Order block score on 5m bars."""
    if i<2 or at<1e-12:return 0.0
    sc=0.0
    for j in range(max(0,i-lb),i):
        if j+1>=len(c):break
        disp=abs(c[j+1]-o[j+1])/at
        if disp<1.5:continue
        # Bullish OB
        if c[j]<o[j] and c[j+1]>o[j+1]:
            if l[j]<=c[i]<=h[j]:
                age=i-j;sc=max(sc,0.4+0.6*max(0,1-age/25))
        # Bearish OB
        if c[j]>o[j] and c[j+1]<o[j+1]:
            if l[j]<=c[i]<=h[j]:
                age=i-j;sc=max(sc,0.4+0.6*max(0,1-age/25))
    return sc

def struct_5m(h,l,c,i,sw=12):
    """BOS/CHoCH on 5m bars."""
    if i<sw*4:return 0.0
    shs=[];sls=[]
    for j in range(sw,min(i-sw,i)):
        rng=range(max(0,j-sw),min(len(h),j+sw+1))
        if all(h[j]>=h[k] for k in rng if k!=j):shs.append((j,h[j]))
        if all(l[j]<=l[k] for k in rng if k!=j):sls.append((j,l[j]))
    if len(shs)<2:return 0.0
    if shs[-1][1]>shs[-2][1] and c[i]>shs[-1][1]:
        return min(0.8,0.4+0.4*max(0,1-(i-shs[-1][0])/30))
    if len(sls)>=2 and sls[-1][1]<sls[-2][1] and c[i]<sls[-1][1]:
        return min(0.8,0.4+0.4*max(0,1-(i-sls[-1][0])/30))
    return 0.0

# ── Coin profiles ──
PROFILES={
    "BTCUSDT":{"ef":10,"es":21,"adx":33,"sl":1.0,"rr":0.5,"hb":72,"side":"long","lev":20},
    "ETHUSDT":{"ef":8,"es":21,"adx":45,"sl":4.0,"rr":1.5,"hb":576,"side":"both","lev":20,
               "s_ef":10,"s_es":21,"s_adx":35,"s_sl":4.0,"s_rr":1.5,"s_hb":288},
    "SOLUSDT":{"ef":20,"es":50,"adx":45,"sl":4.0,"rr":1.5,"hb":576,"side":"both","lev":20,
               "s_ef":20,"s_es":50,"s_adx":35,"s_sl":4.0,"s_rr":1.5,"s_hb":288},
    "XRPUSDT":{"ef":9,"es":21,"adx":40,"sl":4.0,"rr":0.5,"hb":576,"side":"both","lev":7},
}

@dataclass
class T:
    sym:str="";side:str="";ei:int=0;ep:float=0;xi:int=0;xp:float=0;xr:str=""
    lev:int=12;not_:float=0;sp:float=0;pk:float=0;pnl:float=0;src:str="regime"

def _close(t,cost):
    if not t.xp or t.ep<=0:return
    r=(t.xp/t.ep-1) if t.side=="long" else -(t.xp/t.ep-1)
    t.pnl=t.not_*r-t.not_*cost/10000

@dataclass
class Mode:
    name:str;oi:bool=False;smc:bool=False;vwap:bool=False;alpha:bool=False

def run5m(o,h,l,c,v,oi,sym,mode,eq=75,cost=24):
    """5m bar backtest using validated coin profile."""
    p=PROFILES.get(sym)
    if not p:return []
    trades=[];pos=None;cd=0;dl=0.0;dd="";cl=0
    r1=eq*0.0075;n=len(c)
    # 1h = 12 5m bars. Pre-compute 1h EMAs at 5m resolution
    # We compute EMA on 1h closes (every 12th bar)
    h1_c=[];h1_h=[];h1_l=[]
    for i in range(0,n,12):
        end=min(i+12,n)
        h1_c.append(c[end-1])
        h1_h.append(max(h[i:end]))
        h1_l.append(min(l[i:end]))

    _oid=0.0;_smc=0.0;_vz=0.0;_vw=0.0
    for i in range(max(600,p["es"]*12+24),n):
        d=str(i//(24*12))
        if d!=dd:dl=0;dd=d
        # Exit
        if pos is not None:
            hi_=h[i];lo_=l[i];cl_=c[i];ep=pos.ep;lv=pos.lev;sp_=pos.sp
            if pos.side=="long":bst=(hi_/ep-1)*100*lv;wst=(lo_/ep-1)*100*lv;cur=(cl_/ep-1)*100*lv
            else:bst=-(lo_/ep-1)*100*lv;wst=-(hi_/ep-1)*100*lv;cur=-(cl_/ep-1)*100*lv
            pos.pk=max(pos.pk,bst)
            pr=p if pos.src=="regime" else {"sl":1.2,"rr":1.5,"hb":144}  # alpha defaults
            sl_r=pr.get("s_sl",pr["sl"]) if pos.side=="short" and "s_sl" in pr else pr["sl"]
            rr_=pr.get("s_rr",pr["rr"]) if pos.side=="short" and "s_rr" in pr else pr["rr"]
            hb_=pr.get("s_hb",pr["hb"]) if pos.side=="short" and "s_hb" in pr else pr["hb"]
            sl_hit=-sp_*100*lv*sl_r;tp_hit=sp_*100*lv*rr_
            if pos.pk>=sp_*100*lv*0.5:sl_hit=sp_*100*lv*0.05  # BE after 0.5R
            if wst<=sl_hit:
                pos.xp=ep*(1+sl_hit/100/lv) if pos.side=="long" else ep*(1-sl_hit/100/lv)
                pos.xi=i;pos.xr="SL";_close(pos,cost);trades.append(pos)
                dl+=pos.pnl;cl=cl+1 if pos.pnl<=0 else 0;cd=i+36;pos=None;continue
            if bst>=tp_hit:
                pos.xp=ep*(1+tp_hit/100/lv) if pos.side=="long" else ep*(1-tp_hit/100/lv)
                pos.xi=i;pos.xr="TP";_close(pos,cost);trades.append(pos);dl+=pos.pnl;cl=0;cd=i+12;pos=None;continue
            if i-pos.ei>=hb_:
                pos.xi=i;pos.xp=cl_;pos.xr="TIME";_close(pos,cost);trades.append(pos);dl+=pos.pnl;pos=None;continue
            # Alpha VWAP target
            if pos.src=="alpha_vwap":
                vz,_=vwap_z_5m(h,l,c,v,i)
                if abs(vz)<0.5:
                    pos.xi=i;pos.xp=cl_;pos.xr="VWAP_TGT";_close(pos,cost);trades.append(pos);dl+=pos.pnl;pos=None;continue
            continue

        if i<cd:continue
        if dl<=-2*r1:continue
        if cl>=3:cl=0;cd=i+72;continue

        # ── 1h indicators from 5m ──
        i1=i//12
        if i1<max(p["es"]+2,50):continue
        ef=ema(h1_c[:i1+1],p["ef"]);es=ema(h1_c[:i1+1],p["es"])
        adx_=adx_bars(h1_h[:i1+1],h1_l[:i1+1],h1_c[:i1+1],14) if i1>16 else 0
        at=atr_bars(h[:i+1],l[:i+1],c[:i+1],14*12)  # 14-period on 5m (=70min ATR)
        at_1h=atr_bars(h1_h[:i1+1],h1_l[:i1+1],h1_c[:i1+1],14)  # 1h ATR

        # Trend direction from EMA
        long_ok=(ef>es and c[i]>es) if p["side"] in ("long","both") else False
        short_ok=(ef<es and c[i]<es) if p["side"]=="both" else False

        # ADX gate
        sd=""
        if long_ok and adx_>=p["adx"]:sd="long"
        if short_ok and adx_>=p.get("s_adx",p["adx"]):sd="short"

        # EMA cross confirmation on 5m
        ef5=ema(c[max(0,i-60):i+1],min(12,max(3,p["ef"])))
        es5=ema(c[max(0,i-120):i+1],min(24,max(6,p["es"])))
        if sd=="long" and ef5<=es5:sd=""
        if sd=="short" and ef5>=es5:sd=""

        # ── Signal quality from new features (computed every 12 bars = 1h) ──
        if i%12==0 or i==max(600,p["es"]*12+24):
            _oid=0.0;_smc=0.0;_vz=0.0;_vw=0.0
            if mode.oi and oi:
                _oid=oi_div_5m(oi,c,i,288)
            if mode.smc:
                fg=fvg_5m(h,l,i,40);ob_=ob_5m(h,l,c,o,at,i,30);st=struct_5m(h,l,c,i,8)
                _smc=0.3*fg+0.3*ob_+0.4*st
            if mode.vwap:
                _vz,_vw=vwap_z_5m(h,l,c,v,i,144)  # 12h VWAP for speed
        oid=_oid;smc_s=_smc;vz=_vz;vw=_vw

        # ── OI Filter: block fake breakouts ──
        if mode.oi and sd and oid<-0.4:
            sd=""  # hard block

        # ── Regime entry ──
        if sd:
            sp=max(0.005,at_1h/c[i]) if at_1h>0 else 0.01
            lev=p["lev"]
            sm=1.0
            # SMC boost
            if mode.smc and smc_s>0.4:sm*=1.0+smc_s*0.25
            # OI confirmation boost
            if mode.oi and oid>0.4:
                sm*=1.1;lev=min(lev+2,20)
            # VWAP gate: in trend, penalize far-from-VWAP entries
            if mode.vwap and abs(vz)>2.0:sm*=0.7
            # VWAP pullback boost
            if mode.vwap and sd=="long" and -1.5<vz<-0.3:sm*=1.15
            if mode.vwap and sd=="short" and 0.3<vz<1.5:sm*=1.15
            not_=r1/sp*min(sm,1.5)
            pos=T(sym=sym,side=sd,ei=i,ep=c[i],lev=lev,not_=not_,sp=sp,src="regime")
            continue

        # ── Alpha entries (regime = cash) ──
        if mode.alpha and not sd:
            # A1: VWAP Mean Reversion (ranging only)
            if mode.vwap and adx_<15 and abs(vz)>=2.5 and abs(oid)<0.3:
                vol_ok=v[i]>0.7*sum(v[max(0,i-60):i])/max(len(v[max(0,i-60):i]),1) if i>60 else True
                if vol_ok:
                    asd="short" if vz>0 else "long"
                    sp=max(0.006,1.2*at/c[i]);not_=r1/sp*0.35
                    pos=T(sym=sym,side=asd,ei=i,ep=c[i],lev=3,not_=not_,sp=sp,src="alpha_vwap")
                    cd=i+48;continue

            # A2: SMC FVG Fill
            if mode.smc and smc_s>0.55 and 35<rsi_bars(c[:i+1])<65:
                e3=ema(c[max(0,i-15):i+1],3);e8=ema(c[max(0,i-30):i+1],8)
                if e3>e8:asd="long"
                elif e3<e8:asd="short"
                else:continue
                sp=max(0.005,0.8*at/c[i]);not_=r1/sp*0.4*smc_s
                pos=T(sym=sym,side=asd,ei=i,ep=c[i],lev=5,not_=not_,sp=sp,src="alpha_smc")
                cd=i+36;continue

            # A3: OI Momentum Surge
            if mode.oi and oid>0.5 and adx_>=18 and i>=36:
                mom3=(c[i]-c[i-36])/c[i-36] if c[i-36]>0 else 0
                if abs(mom3)>0.003:
                    asd="long" if mom3>0 else "short"
                    sp=max(0.006,at/c[i]);not_=r1/sp*0.5
                    pos=T(sym=sym,side=asd,ei=i,ep=c[i],lev=7,not_=not_,sp=sp,src="alpha_oi")
                    cd=i+36;continue

    if pos:
        pos.xi=n-1;pos.xp=c[-1];pos.xr="END";_close(pos,cost);trades.append(pos)
    return trades

def wf(ts,n=4):
    if len(ts)<n*3:return {"v":False,"f":[],"p":0}
    s=sorted(ts,key=lambda t:t.ei);fs=len(s)//n;folds=[]
    for i in range(n):
        f=s[i*fs:(i+1)*fs if i<n-1 else len(s)]
        pnl=sum(t.pnl for t in f);wr=sum(1 for t in f if t.pnl>0)/max(len(f),1)
        folds.append({"q":i+1,"n":len(f),"pnl":round(pnl,2),"wr":round(wr,4)})
    return {"v":sum(1 for f in folds if f["pnl"]>0)>=3,"f":folds,"p":sum(1 for f in folds if f["pnl"]>0)}

def mc(ts,eq=75,ns=1000):
    if len(ts)<10:return {"ruin":100,"mdd":100,"final":0}
    pnls=[t.pnl for t in ts];rc=0;dds=[];fins=[]
    for _ in range(ns):
        sh=random.sample(pnls,len(pnls));e=eq;pk=eq;mdd=0;r=False
        for p in sh:
            e+=p;pk=max(pk,e);dd=(pk-e)/pk if pk>0 else 0;mdd=max(mdd,dd)
            if e<=0:r=True;break
        if r:rc+=1
        dds.append(mdd*100);fins.append(e)
    return {"ruin":round(rc/ns*100,2),"mdd":round(statistics.median(dds),1),"final":round(statistics.mean(fins),2)}

def main():
    syms=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT"]
    eq=75;cost=24.0;dd=Path("quant_runtime/historical")
    modes=[
        Mode("baseline"),
        Mode("+OI",oi=True),
        Mode("+OI+SMC",oi=True,smc=True),
        Mode("+OI+SMC+VWAP",oi=True,smc=True,vwap=True),
        Mode("FULL+alpha",oi=True,smc=True,vwap=True,alpha=True),
    ]
    sym_data={}
    for sym in syms:
        sp=dd/sym
        b5=json.load(open(sp/"5m.json"))
        o_=[b["open_price"] for b in b5];h_=[b["high_price"] for b in b5]
        l_=[b["low_price"] for b in b5];c_=[b["close_price"] for b in b5]
        v_=[b.get("base_volume",b.get("quote_volume",0)) for b in b5]
        n_=len(c_)
        # Real OI data
        oip=sp/"oi_1h.json"
        if oip.exists():
            oir=json.load(open(oip))
            oim={int(r["timestamp"]):float(r["open_interest"]) for r in oir}
            bt=[int(b.get("open_time",0)) for b in b5]
            oia=[];last=list(oim.values())[0] if oim else 50
            for t in bt:
                # Find nearest OI (within 1h = 3600000ms)
                near=min(oim.keys(),key=lambda k:abs(k-t),default=None)
                if near and abs(near-t)<3600000:last=oim[near]
                oia.append(last)
        else:
            oia=[50.0]*n_
        print(f"  {sym}: {n_:,} 5m bars, OI: {len([x for x in oia if x!=50])} real pts",flush=True)
        sym_data[sym]=(o_,h_,l_,c_,v_,oia)

    print(f"\n{'='*130}")
    print(f"{'5-MINUTE BACKTEST: VALIDATED PROFILES + ALPHA STRATEGIES':^130}")
    print(f"{'='*130}")
    print(f"  Symbols: {', '.join(syms)} | Equity: ${eq} | Cost: {cost}bps | 103K bars/sym\n")

    results=[]
    for mode in modes:
        t0=time.time()
        all_t=[]
        for sym,(o_,h_,l_,c_,v_,oia) in sym_data.items():
            ts=run5m(o_,h_,l_,c_,v_,oia,sym,mode,eq,cost)
            all_t.extend(ts)
        el=time.time()-t0
        nt=len(all_t)
        if nt==0:
            results.append({"m":mode.name,"n":0,"wr":0,"pnl":0,"pf":0,"ev":0,
                           "wf":{"v":False,"p":0},"mc":{"ruin":100},"rn":0,"an":0,"ap":0,"t":el})
            continue
        w=sum(1 for t in all_t if t.pnl>0);pnl=sum(t.pnl for t in all_t)
        gp=sum(t.pnl for t in all_t if t.pnl>0);gl=abs(sum(t.pnl for t in all_t if t.pnl<=0))
        pf=gp/max(gl,0.01);wr=w/max(nt,1);ev=pnl/nt
        rn=sum(1 for t in all_t if t.src=="regime");an=sum(1 for t in all_t if "alpha" in t.src)
        ap=sum(t.pnl for t in all_t if "alpha" in t.src)
        aw=sum(t.pnl for t in all_t if t.pnl>0 and "alpha" in t.src)
        al_=abs(sum(t.pnl for t in all_t if t.pnl<=0 and "alpha" in t.src))
        wf_=wf(all_t);mc_=mc(all_t,eq)
        results.append({"m":mode.name,"n":nt,"wr":round(wr,4),"pnl":round(pnl,2),"pf":round(pf,2),
                        "ev":round(ev,4),"wf":wf_,"mc":mc_,"rn":rn,"an":an,"ap":round(ap,2),
                        "t":round(el,1)})
        # Per-source breakdown
        for src in set(t.src for t in all_t):
            st=[t for t in all_t if t.src==src]
            sp_=sum(t.pnl for t in st);sw=sum(1 for t in st if t.pnl>0)
            sg=sum(t.pnl for t in st if t.pnl>0);sl_=abs(sum(t.pnl for t in st if t.pnl<=0))
            print(f"    {src:15s}: {len(st):>4}t WR={sw/max(len(st),1)*100:.1f}% PnL=${sp_:>+8.2f} PF={sg/max(sl_,0.01):.2f}",flush=True)
        # Per-symbol
        for sym in syms:
            st=[t for t in all_t if t.sym==sym]
            if st:
                sp_=sum(t.pnl for t in st);sw=sum(1 for t in st if t.pnl>0)
                print(f"    {sym:15s}: {len(st):>4}t WR={sw/max(len(st),1)*100:.1f}% PnL=${sp_:>+8.2f}",flush=True)
        print(f"    [{mode.name} done in {el:.1f}s]",flush=True)

    # ── Summary ──
    print(f"\n{'='*130}")
    print(f"{'Mode':<20} {'N':>5} {'Reg':>4} {'Alp':>4} {'WR%':>6} {'PnL$':>9} {'EV/t$':>7} {'PF':>5} {'WF':>3} {'MC%':>5} {'MDD%':>5} {'AlpPnL$':>9}")
    print("-"*100)
    for r in results:
        wfs=f"{r['wf'].get('p',0)}/4";mcs=f"{r['mc'].get('ruin',100):.1f}"
        mdds=f"{r['mc'].get('mdd',100):.1f}"
        print(f"{r['m']:<20} {r['n']:>5} {r.get('rn',0):>4} {r.get('an',0):>4} "
              f"{r['wr']*100:>6.1f} {r['pnl']:>9.2f} {r['ev']:>7.4f} {r['pf']:>5.2f} "
              f"{wfs:>3} {mcs:>5} {mdds:>5} {r.get('ap',0):>9.2f}")

    # WF details
    print(f"\nWALK-FORWARD:")
    for r in results:
        if r.get("wf",{}).get("f"):
            qs=" | ".join(f"Q{f['q']}:{f['n']}t ${f['pnl']:+.1f}" for f in r["wf"]["f"])
            print(f"  {r['m']:<20} {qs}  {'PASS' if r['wf']['v'] else 'FAIL'}")

    # Cost stress on best
    best=max(results,key=lambda r:r["pnl"])
    bm=[m for m in modes if m.name==best["m"]][0]
    print(f"\nCOST STRESS ({best['m']}):")
    for cb in [12,18,24,34,44]:
        at=[]
        for sym,(o_,h_,l_,c_,v_,oia) in sym_data.items():
            at.extend(run5m(o_,h_,l_,c_,v_,oia,sym,bm,eq,float(cb)))
        p=sum(t.pnl for t in at);w=sum(1 for t in at if t.pnl>0)/max(len(at),1)
        g=sum(t.pnl for t in at if t.pnl>0);l_=abs(sum(t.pnl for t in at if t.pnl<=0))
        print(f"  {cb}bps: ${p:>+8.2f} WR={w*100:.1f}% N={len(at)} PF={g/max(l_,0.01):.2f}")

    # Save
    out=Path("quant_runtime/output/backtest_5m_alpha_results.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    json.dump(results,open(out,"w"),indent=2,default=str)
    print(f"\nSaved: {out}")

if __name__=="__main__":
    main()
