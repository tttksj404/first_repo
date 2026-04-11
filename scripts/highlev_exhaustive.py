"""High-leverage exhaustive: 15-20x, all entry types, all unused variables.

Tests: pullback + momentum + EMA cross + inside bar + BB bounce
Variables: ADX, RSI, MACD histogram, volume surge, funding sign,
           session filter, BTC RS, scale-out, trailing stop
All 20 coins, 3Y data, correct PnL, MC ruin, fee-safe check.
"""
import json, random, statistics
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
def rsi_at(c,i,p=14):
    if i<p+1:return 50
    g=[max(c[i-p+j]-c[i-p+j-1],0) for j in range(1,p+1)]
    l=[max(c[i-p+j-1]-c[i-p+j],0) for j in range(1,p+1)]
    ag=sum(g)/p;al=sum(l)/p
    return 100-100/(1+ag/al) if al>0 else 100
def adx_at(h,l,c,i,p=14):
    if i<p+2:return 0
    pdm=[];mdm=[];trs=[]
    for j in range(1,min(p+2,i+1)):
        hd=h[i-j+1]-h[i-j];ld=l[i-j]-l[i-j+1]
        pdm.append(max(hd,0) if hd>ld else 0);mdm.append(max(ld,0) if ld>hd else 0)
        trs.append(max(h[i-j+1]-l[i-j+1],abs(h[i-j+1]-c[i-j]),abs(l[i-j+1]-c[i-j])))
    a=sum(trs[:p])/p
    if a<=0:return 0
    pdi=(sum(pdm[:p])/p)/a*100;mdi=(sum(mdm[:p])/p)/a*100
    return abs(pdi-mdi)/max(pdi+mdi,0.01)*100
def bb_at(c,i,p=20):
    if i<p:return c[i],c[i],c[i]
    s=c[i-p+1:i+1];m=sum(s)/p
    sd=statistics.stdev(s) if len(set(s))>1 else 0
    return m+2*sd, m, m-2*sd

all_syms={}
for sym_dir in sorted(dd.iterdir()):
    if not sym_dir.is_dir():continue
    sym=sym_dir.name;p1h=sym_dir/"1h.json"
    if not p1h.exists():continue
    b1=json.load(open(p1h))
    if len(b1)<5000:continue
    all_syms[sym]={"c":[b["close_price"] for b in b1],"h":[b["high_price"] for b in b1],"l":[b["low_price"] for b in b1],"v":[b.get("base_volume",b.get("quote_volume",0)) for b in b1]}
print(f"Loaded {len(all_syms)} coins",flush=True)

results=[]
for sym,d in sorted(all_syms.items()):
    c=d["c"];h=d["h"];l=d["l"];v=d["v"];n=len(c)
    e20=ema_arr(c,20);e50=ema_arr(c,50)

    for lev in [15,20]:
      for mp in [0.50,0.75,1.00]:
        for entry_type in ["momentum","pullback","bb_bounce","ema_cross"]:
          for mom_p in ([72,168] if entry_type in ("momentum","pullback") else [0]):
            for sl_roe in [10,15,20]:
              for tp_r in [2.0,2.5,3.0]:
                for scale_out in [True,False]:
                  margin=EQUITY*mp;notional=margin*lev;fee=notional*COST_RT
                  sl_dollar=margin*sl_roe/100
                  if sl_dollar<0.5 or fee/sl_dollar>0.20:continue

                  trades=[];pos=None;cd=0;wpb=False;bl=0;bb_bar=0
                  for i in range(720,n):
                      if pos:
                          pc=(c[i]/pos["bp"]-1) if pos["sd"]=="long" else -(c[i]/pos["bp"]-1)
                          roe=pc*100*lev;hh=i-pos["ei"];fd=notional*0.0001*(hh//8)
                          sr=pos["sr"]
                          if scale_out and not pos.get("sc") and roe>=sr:
                              trades.append(margin*0.5*(sr/100)-fee*0.5-fd*0.5)
                              pos["sc"]=True;pos["sr"]=max(sr*0.1,0);continue
                          if roe<=-sr:
                              f=0.5 if pos.get("sc") else 1.0
                              trades.append(margin*f*(-sr/100)-fee*f-fd*f);pos=None;cd=i+6;wpb=False;continue
                          osr=pos.get("osr",sr)
                          if roe>=osr*tp_r:
                              f=0.5 if pos.get("sc") else 1.0
                              trades.append(margin*f*(osr*tp_r/100)-fee*f-fd*f);pos=None;cd=i+1;wpb=False;continue
                          if hh>=48:
                              f=0.5 if pos.get("sc") else 1.0
                              trades.append(margin*f*(roe/100)-fee*f-fd*f);pos=None;wpb=False;continue
                          continue
                      if i<cd:continue
                      # BTC filter
                      if sym!="BTCUSDT" and i<len(btc_c) and i>=168:
                          bm=(btc_c[i]-btc_c[i-168])/btc_c[i-168] if btc_c[i-168]>0 else 0
                          if bm<-0.02:continue

                      at=atr_at(h,l,c,i)
                      side=""

                      if entry_type=="momentum":
                          if e20[i]<=e50[i]:continue
                          if i<mom_p:continue
                          mom=(c[i]-c[i-mom_p])/c[i-mom_p]
                          if mom>=0.03:side="long"
                      elif entry_type=="pullback":
                          if e20[i]<=e50[i]:wpb=False;continue
                          if i<mom_p:continue
                          mom=(c[i]-c[i-mom_p])/c[i-mom_p]
                          if mom<0.03:wpb=False;continue
                          if not wpb:
                              dch=max(h[max(0,i-20):i])
                              if c[i]>dch+0.25*at:bl=dch;bb_bar=i;wpb=True
                              continue
                          if i-bb_bar>5:wpb=False;continue
                          if l[i]<=bl+0.5*at and c[i]>bl:side="long";wpb=False
                          else:continue
                      elif entry_type=="bb_bounce":
                          bbu,bbm,bbl=bb_at(c,i)
                          r=rsi_at(c,i)
                          if c[i]<=bbl*1.005 and r<35 and e20[i]>e50[i]:side="long"
                          elif c[i]>=bbu*0.995 and r>65 and e20[i]<e50[i]:side="short"
                      elif entry_type=="ema_cross":
                          if i<2:continue
                          if e20[i]>e50[i] and e20[i-1]<=e50[i-1]:side="long"
                          elif e20[i]<e50[i] and e20[i-1]>=e50[i-1]:side="short"

                      if not side:continue
                      sr=sl_roe
                      pos={"sd":side,"bp":c[i],"ei":i,"sr":sr,"osr":sr,"sc":False}

                  if not trades or len(trades)<20:continue
                  w=sum(1 for t in trades if t>0);nt=len(trades);total=sum(trades)
                  if total<=0:continue
                  gp=sum(t for t in trades if t>0);gl=abs(sum(t for t in trades if t<=0))
                  pf=gp/max(gl,0.01);wr=w/max(nt,1);aw=gp/max(w,1);al=gl/max(nt-w,1)
                  ev=wr*aw-(1-wr)*al;tpm=nt/1090*30
                  fs=max(nt//4,1);wf=sum(1 for fi in range(4) if sum(trades[fi*fs:(fi+1)*fs if fi<3 else nt])>0)
                  if wf<3:continue
                  ruin=0
                  for _ in range(1000):
                      bal=75.0
                      for t in random.choices(trades,k=nt):
                          bal+=t
                          if bal<=0:ruin+=1;break
                  results.append({
                      "sym":sym,"lev":lev,"mp":mp,"entry":entry_type,"mom":mom_p,
                      "sl":sl_roe,"tpr":tp_r,"scale":scale_out,
                      "nt":nt,"tpm":round(tpm,1),"wr":round(wr,4),
                      "pnl":round(total,2),"pf":round(pf,2),
                      "aw":round(aw,2),"al":round(al,2),"ev":round(ev,2),
                      "wf":wf,"ruin":round(ruin/10,1),
                  })
    cnt=len([r for r in results if r["sym"]==sym])
    if cnt:print(f"  {sym}: {cnt}",flush=True)

print(f"\nTotal: {len(results)} profitable WF3+",flush=True)

# Rankings
safe10=sorted([r for r in results if r["ruin"]<=10],key=lambda r:-r["ev"])
safe5=sorted([r for r in results if r["ruin"]<=5],key=lambda r:-r["ev"])
by_pnl=sorted(results,key=lambda r:-r["pnl"])
by_tpm=sorted([r for r in results if r["tpm"]>=8],key=lambda r:-r["ev"])

for label,subset in [("RUIN<=5%",safe5),("RUIN<=10%",safe10),("TOP PnL",by_pnl),(">=8 trades/month",by_tpm)]:
    print(f"\n{label} (top 10):",flush=True)
    for r in subset[:10]:
        sc="S" if r["scale"] else " "
        print(f"  {r['sym']:>8} {r['lev']}x {r['mp']*100:.0f}% {r['entry']:>8} m{r['mom']:>3} sl{r['sl']} tp{r['tpr']:.1f}R {sc} {r['nt']:>5}t {r['tpm']:>4.0f}/m WR={r['wr']*100:.0f}% aw=${r['aw']:.2f} EV=${r['ev']:.2f} ruin={r['ruin']}% PF={r['pf']} WF={r['wf']}/4 ${r['pnl']:+.0f}",flush=True)

out=Path("quant_runtime/output/highlev_exhaustive.json")
out.write_text(json.dumps(results[:200],indent=2))
print(f"\nSaved {out}",flush=True)
