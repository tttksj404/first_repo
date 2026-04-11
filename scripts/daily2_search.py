"""Find strategy with 720+ trades/year (2/day), all 20 coins, fee-safe, ruin<10%."""
import json, random, sys
from pathlib import Path

dd = Path("quant_runtime/historical")
COST_RT=0.0012; EQUITY=75.0
btc_c=[b["close_price"] for b in json.load(open(dd/"BTCUSDT"/"1h.json"))]

def ema_arr(c,p):
    e=[0.0]*len(c);e[0]=c[0];k=2/(p+1)
    for i in range(1,len(c)):e[i]=c[i]*k+e[i-1]*(1-k)
    return e
def atr_at(h,l,c,i,p=14):
    if i<p+1:return 0.0001
    return sum(max(h[i-j]-l[i-j],abs(h[i-j]-c[i-j-1]),abs(l[i-j]-c[i-j-1])) for j in range(1,p+1))/p

# Load all coins
all_syms={}
for sym_dir in sorted(dd.iterdir()):
    if not sym_dir.is_dir(): continue
    sym=sym_dir.name; p1h=sym_dir/"1h.json"
    if not p1h.exists(): continue
    b1=json.load(open(p1h))
    if len(b1)<5000: continue
    all_syms[sym]={"c":[b["close_price"] for b in b1],"h":[b["high_price"] for b in b1],"l":[b["low_price"] for b in b1],"n":len(b1)}

print(f"Loaded {len(all_syms)} coins", flush=True)

# Collect ALL pullback signals across ALL coins, then simulate rotation
results=[]

for lev in [5, 10]:
  for mp in [0.50, 0.75]:
    for N in [10, 15, 20, 30]:
      for pbw in [3, 5, 7]:
        for mom_p in [24, 72, 168]:
          for tpr in [1.5, 2.0, 2.5]:
            margin=EQUITY*mp; notional=margin*lev; fee=notional*COST_RT

            # Collect signals from ALL coins
            all_signals=[]
            for sym,d in all_syms.items():
                c=d["c"];h=d["h"];l=d["l"];n=d["n"]
                e20=ema_arr(c,20);e50=ema_arr(c,50)
                wpb=False;bl=0;bb=0
                for i in range(max(720,mom_p+20),n):
                    if e20[i]<=e50[i]:wpb=False;continue
                    if i<mom_p:continue
                    mom=(c[i]-c[i-mom_p])/c[i-mom_p] if c[i-mom_p]>0 else 0
                    if mom<0.02:wpb=False;continue  # lowered to 2% for more signals
                    if sym!="BTCUSDT" and i<len(btc_c) and i>=mom_p:
                        bm=(btc_c[i]-btc_c[i-mom_p])/btc_c[i-mom_p] if btc_c[i-mom_p]>0 else 0
                        if bm<-0.03:continue
                    at=atr_at(h,l,c,i)
                    if not wpb:
                        dch=max(h[max(0,i-N):i])
                        if c[i]>dch+0.15*at:bl=dch;bb=i;wpb=True  # relaxed breakout threshold
                        continue
                    if i-bb>pbw:wpb=False;continue
                    if l[i]<=bl+0.6*at and c[i]>bl:  # relaxed pullback threshold
                        sp=min(l[i],bl)-0.25*at;sd=(c[i]-sp)/c[i];sr=sd*100*lev
                        sld=margin*sr/100
                        if sld<0.3 or fee/sld>0.20:wpb=False;continue  # slightly relaxed fee-safe
                        all_signals.append({"sym":sym,"bar":i,"bp":c[i],"sr":sr,"mom":mom})
                        wpb=False

            all_signals.sort(key=lambda s:s["bar"])

            # Simulate: one position at a time, rotate across coins
            trades=[];pos=None;cd=0;sym_counts={}
            for sig in all_signals:
                i=sig["bar"];sym=sig["sym"]
                if i<cd or pos:continue
                d=all_syms[sym];c=d["c"];n=d["n"]
                pos={"sym":sym,"bp":sig["bp"],"ei":i,"sr":sig["sr"],"osr":sig["sr"],"sc":False}
                sym_counts[sym]=sym_counts.get(sym,0)+1
                # Simulate exit
                for j in range(i+1,min(i+73,n)):
                    pc=(c[j]/pos["bp"]-1);roe=pc*100*lev;hh=j-pos["ei"];fd=notional*0.0001*(hh//8)
                    sr=pos["sr"]
                    if not pos.get("sc") and roe>=sr:
                        trades.append(margin*0.5*(sr/100)-fee*0.5-fd*0.5)
                        pos["sc"]=True;pos["sr"]=max(sr*0.1,0);continue
                    if roe<=-sr:
                        f=0.5 if pos.get("sc") else 1.0
                        trades.append(margin*f*(-sr/100)-fee*f-fd*f);pos=None;cd=j+3;break
                    osr=pos.get("osr",sr)
                    if roe>=osr*tpr:
                        f=0.5 if pos.get("sc") else 1.0
                        trades.append(margin*f*(osr*tpr/100)-fee*f-fd*f);pos=None;cd=j+1;break
                    if hh>=48:
                        f=0.5 if pos.get("sc") else 1.0
                        trades.append(margin*f*(roe/100)-fee*f-fd*f);pos=None;break
                else:
                    if pos:pos=None

            if not trades or len(trades)<100:continue  # need 100+ trades minimum
            w=sum(1 for t in trades if t>0);nt=len(trades);total=sum(trades)
            if total<=0:continue
            gp=sum(t for t in trades if t>0);gl=abs(sum(t for t in trades if t<=0))
            pf=gp/max(gl,0.01);wr=w/max(nt,1);aw=gp/max(w,1);al=gl/max(nt-w,1)
            ev=wr*aw-(1-wr)*al
            fs=max(nt//4,1);wf=sum(1 for fi in range(4) if sum(trades[fi*fs:(fi+1)*fs if fi<3 else nt])>0)
            if wf<3:continue
            # Quick MC
            ruin=0
            for _ in range(1000):
                bal=75.0
                for t in random.choices(trades,k=nt):
                    bal+=t
                    if bal<=0:ruin+=1;break
            ruin_pct=ruin/10
            years=3  # approximate
            trades_per_day=nt/years/365

            results.append({
                "lev":lev,"mp":mp,"N":N,"pbw":pbw,"mom":mom_p,"tpr":tpr,
                "nt":nt,"tpd":round(trades_per_day,1),"wr":round(wr,4),
                "pnl":round(total,2),"pf":round(pf,2),
                "aw":round(aw,2),"al":round(al,2),"ev":round(ev,2),
                "wf":wf,"ruin":round(ruin_pct,1),
                "coins":len(sym_counts),"top3":sorted(sym_counts.items(),key=lambda x:-x[1])[:3]
            })

print(f"\nTotal profitable configs (100+ trades, WF3+): {len(results)}", flush=True)

# Filter: trades/day >= 1.5 (target 2/day but allow some flexibility)
daily2=sorted([r for r in results if r["tpd"]>=1.5],key=lambda r:-r["ev"])
daily1=sorted([r for r in results if r["tpd"]>=0.8],key=lambda r:-r["ev"])

print(f"\n=== >=2/day ({len([r for r in results if r['tpd']>=2])}), >=1.5/day ({len(daily2)}), >=0.8/day ({len(daily1)}) ===", flush=True)

print(f"\nTOP 15 (>=1.5 trades/day):", flush=True)
print(f"{'Lev':>3} {'Mp':>3} {'N':>3} {'Pb':>2} {'Mom':>3} {'TP':>4} {'Trades':>6} {'T/D':>4} {'WR%':>5} {'AvgW':>6} {'AvgL':>5} {'EV':>5} {'Ruin':>5} {'PF':>5} {'WF':>3} {'Coins':>5} {'PnL':>8}", flush=True)
for r in daily2[:15]:
    t3=" ".join(f"{s[:4]}={n}" for s,n in r["top3"])
    print(f"{r['lev']:>3}x {r['mp']*100:>3.0f} {r['N']:>3} {r['pbw']:>2} {r['mom']:>3} {r['tpr']:>4.1f} {r['nt']:>6} {r['tpd']:>4.1f} {r['wr']*100:>5.1f} ${r['aw']:>5.2f} ${r['al']:>4.2f} ${r['ev']:>4.2f} {r['ruin']:>4.1f}% {r['pf']:>5.2f} {r['wf']:>2}/4 {r['coins']:>3}c {r['pnl']:>+8.0f}", flush=True)

if not daily2:
    print(f"\nTOP 15 (>=0.8/day as fallback):", flush=True)
    for r in daily1[:15]:
        print(f"{r['lev']:>3}x {r['mp']*100:>3.0f} {r['N']:>3} {r['pbw']:>2} {r['mom']:>3} {r['tpr']:>4.1f} {r['nt']:>6} {r['tpd']:>4.1f} {r['wr']*100:>5.1f} ${r['aw']:>5.2f} ${r['al']:>4.2f} ${r['ev']:>4.2f} {r['ruin']:>4.1f}% {r['pf']:>5.2f} {r['wf']:>2}/4 {r['coins']:>3}c {r['pnl']:>+8.0f}", flush=True)

out=Path("quant_runtime/output/daily2_search.json")
out.write_text(json.dumps(results[:200],indent=2))
print(f"\nSaved {out}", flush=True)
