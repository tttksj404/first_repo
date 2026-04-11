"""Hybrid B: Momentum + Pullback + Scale-out + ADX + BTC RS filter.
Combines best elements from all tested strategies.
"""
import json, random, sys
from pathlib import Path

dd = Path("quant_runtime/historical")
COST_RT = 0.0012; EQUITY = 75.0

def ema_arr(c, p):
    e=[0.0]*len(c); e[0]=c[0]; k=2/(p+1)
    for i in range(1,len(c)): e[i]=c[i]*k+e[i-1]*(1-k)
    return e

def atr_at(h,l,c,i,p=14):
    if i<p+1: return 0.0001
    return sum(max(h[i-j]-l[i-j],abs(h[i-j]-c[i-j-1]),abs(l[i-j]-c[i-j-1])) for j in range(1,p+1))/p

def adx_at(h,l,c,i,p=14):
    if i<p+2: return 0
    pdm=[];mdm=[];trs=[]
    for j in range(1,min(p+2,i+1)):
        hd=h[i-j+1]-h[i-j];ld=l[i-j]-l[i-j+1]
        pdm.append(max(hd,0) if hd>ld else 0);mdm.append(max(ld,0) if ld>hd else 0)
        trs.append(max(h[i-j+1]-l[i-j+1],abs(h[i-j+1]-c[i-j]),abs(l[i-j+1]-c[i-j])))
    a=sum(trs[:p])/p
    if a<=0: return 0
    pdi=(sum(pdm[:p])/p)/a*100;mdi=(sum(mdm[:p])/p)/a*100
    return abs(pdi-mdi)/max(pdi+mdi,0.01)*100

all_syms = {}
btc_c = [b["close_price"] for b in json.load(open(dd/"BTCUSDT"/"1h.json"))]
for sym_dir in sorted(dd.iterdir()):
    if not sym_dir.is_dir(): continue
    sym = sym_dir.name; p1h = sym_dir/"1h.json"
    if not p1h.exists(): continue
    b1=json.load(open(p1h))
    if len(b1)<10000: continue
    all_syms[sym] = {"c":[b["close_price"] for b in b1],"h":[b["high_price"] for b in b1],"l":[b["low_price"] for b in b1]}

print(f"Loaded {len(all_syms)} coins", flush=True)
results = []

for sym, d in sorted(all_syms.items()):
    c=d["c"];h=d["h"];l=d["l"];n=len(c)
    e20=ema_arr(c,20); e50=ema_arr(c,50)
    for lev in [3, 5, 10]:
      for mp in [0.50, 0.75]:
        for adx_floor in [20, 25, 30]:
          for pbw in [3, 5]:
            margin=EQUITY*mp; notional=margin*lev; fee=notional*COST_RT
            trades=[]; pos=None; cd=0; bl=0; bb=0; wpb=False
            for i in range(720, n):
                if pos:
                    pc=(c[i]/pos["bp"]-1) if pos["sd"]=="long" else -(c[i]/pos["bp"]-1)
                    roe=pc*100*lev; hh=i-pos["ei"]; fd=notional*0.0001*(hh//8)
                    sr=pos["sr"]
                    if not pos.get("sc") and roe>=sr:
                        trades.append(margin*0.5*(sr/100)-fee*0.5-fd*0.5)
                        pos["sc"]=True; pos["sr"]=max(sr*0.1,0); continue
                    if roe<=-sr:
                        f=0.5 if pos.get("sc") else 1.0
                        trades.append(margin*f*(-sr/100)-fee*f-fd*f); pos=None; cd=i+6; wpb=False; continue
                    orig_sr=pos.get("orig_sr",sr)
                    if roe>=orig_sr*2.5:
                        f=0.5 if pos.get("sc") else 1.0
                        trades.append(margin*f*(orig_sr*2.5/100)-fee*f-fd*f); pos=None; cd=i+1; wpb=False; continue
                    if hh>=72:
                        f=0.5 if pos.get("sc") else 1.0
                        trades.append(margin*f*(roe/100)-fee*f-fd*f); pos=None; wpb=False; continue
                    continue
                if i<cd: continue
                if e20[i]<=e50[i]: wpb=False; continue
                if i<168: continue
                mom7d=(c[i]-c[i-168])/c[i-168]
                if mom7d<0.03: wpb=False; continue
                adx=adx_at(h,l,c,i)
                if adx<adx_floor: wpb=False; continue
                if sym!="BTCUSDT" and i<len(btc_c) and i>=168:
                    bm=(btc_c[i]-btc_c[i-168])/btc_c[i-168]
                    if bm<-0.02: continue
                at=atr_at(h,l,c,i)
                if not wpb:
                    dc_high=max(h[max(0,i-20):i])
                    if c[i]>dc_high+0.25*at: bl=dc_high; bb=i; wpb=True
                    continue
                if i-bb>pbw: wpb=False; continue
                if l[i]<=bl+0.5*at and c[i]>bl:
                    sp=min(l[i],bl)-0.25*at; sd=(c[i]-sp)/c[i]; sr=sd*100*lev
                    sld=margin*sr/100
                    if sld<0.5 or fee/sld>0.15: wpb=False; continue
                    pos={"sd":"long","bp":c[i],"ei":i,"sr":sr,"orig_sr":sr,"sc":False}; wpb=False

            if not trades or len(trades)<3: continue
            w=sum(1 for t in trades if t>0); nt=len(trades); total=sum(trades)
            if total<=0: continue
            gp=sum(t for t in trades if t>0); gl=abs(sum(t for t in trades if t<=0))
            pf=gp/max(gl,0.01); wr=w/max(nt,1); aw=gp/max(w,1); al=gl/max(nt-w,1)
            fs=max(nt//4,1); wf=sum(1 for fi in range(4) if sum(trades[fi*fs:(fi+1)*fs if fi<3 else nt])>0)
            if wf<3: continue
            ruin=0
            for _ in range(2000):
                bal=75.0
                for t in random.choices(trades,k=nt):
                    bal+=t
                    if bal<=0:ruin+=1;break
            ruin_pct=ruin/20
            results.append({
                "name":f"HYB_{sym}_{lev}x_m{mp*100:.0f}_adx{adx_floor}_pb{pbw}",
                "sym":sym,"lev":lev,"mp":mp,"adx":adx_floor,"pbw":pbw,
                "nt":nt,"wr":round(wr,4),"pnl":round(total,2),"pf":round(pf,2),
                "aw":round(aw,2),"al":round(al,2),"wf":wf,"ruin":round(ruin_pct,1),
                "ev":round(wr*aw-(1-wr)*al,2)
            })
    cnt=len([r for r in results if r["sym"]==sym])
    if cnt: print(f"  {sym}: {cnt} configs", flush=True)

safe=sorted([r for r in results if r["ruin"]<=5],key=lambda r:-r["ev"])
print(f"\nTotal: {len(results)}, ruin<=5%: {len(safe)}", flush=True)
print(f"\nTOP 15 HYBRID (ruin<=5%):", flush=True)
for r in safe[:15]:
    print(f"  {r['name']:>45} {r['nt']:>4}t WR={r['wr']*100:>5.1f} aw=${r['aw']:>6.2f} EV=${r['ev']:>5.2f} ruin={r['ruin']:>4.1f}% PF={r['pf']:>5.2f} WF={r['wf']}/4 PnL=${r['pnl']:>+8.1f}", flush=True)

print(f"\n=== COMPARISON ===", flush=True)
print(f"  Pullback only:  DOGE 10x → EV=$8.83 ruin=3.9%", flush=True)
print(f"  Momentum only:  PEPE 15x → EV=$3.98 ruin=4.2%", flush=True)
if safe:
    print(f"  HYBRID best:    {safe[0]['name']} → EV=${safe[0]['ev']:.2f} ruin={safe[0]['ruin']}%", flush=True)

out=Path("quant_runtime/output/hybrid_results.json")
out.write_text(json.dumps(results[:100],indent=2))
print(f"\nSaved {out}", flush=True)
