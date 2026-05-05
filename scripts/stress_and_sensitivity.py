"""Full validation suite: ruin reduction, cost stress, slippage stress, parameter sensitivity.

Uses the FULL+alpha mode from hantang_alpha as base.
Tests: leverage grid, margin grid, cost grid, slippage grid, TP/SL sensitivity.
"""
import json, random, statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

dd = Path("quant_runtime/historical")
EQUITY = 75.0

def ema_arr(c, p):
    e = [0.0]*len(c); e[0] = c[0]; k = 2/(p+1)
    for i in range(1, len(c)): e[i] = c[i]*k + e[i-1]*(1-k)
    return e

def atr_at(h, l, c, i, p=14):
    if i < p+1: return 0.0001
    return sum(max(h[i-j]-l[i-j], abs(h[i-j]-c[i-j-1]), abs(l[i-j]-c[i-j-1])) for j in range(1, p+1))/p

def adx_at(h, l, c, i, p=14):
    if i < p+2: return 0
    pdm=[]; mdm=[]; trs=[]
    for j in range(1, min(p+2, i+1)):
        hd=h[i-j+1]-h[i-j]; ld=l[i-j]-l[i-j+1]
        pdm.append(max(hd,0) if hd>ld else 0); mdm.append(max(ld,0) if ld>hd else 0)
        trs.append(max(h[i-j+1]-l[i-j+1], abs(h[i-j+1]-c[i-j]), abs(l[i-j+1]-c[i-j])))
    a=sum(trs[:p])/p
    if a<=0: return 0
    pdi=(sum(pdm[:p])/p)/a*100; mdi=(sum(mdm[:p])/p)/a*100
    return abs(pdi-mdi)/max(pdi+mdi,0.01)*100

def vwap_at(h, l, c, v, i, n=96):
    s=max(0,i-n+1); cpv=0; cv=0
    for j in range(s, i+1):
        tp=(h[j]+l[j]+c[j])/3; cpv+=tp*v[j]; cv+=v[j]
    return cpv/max(cv, 1e-12)

def oi_div_at(oi, c, i, lb=24):
    if i<lb or not oi or i>=len(oi): return 0.0
    prices=c[i-lb:i+1]; ois=oi[max(0,i-lb):i+1]
    if len(ois)<lb: return 0.0
    cp=prices[-1]; ph=max(prices[:-1]); pl=min(prices[:-1])
    on=ois[-1]; oa=sum(ois[:-1])/max(len(ois)-1,1)
    od=(on-oa)/max(abs(oa),1e-12)
    if cp>ph and od<-0.015: return -0.6
    if cp>ph and od>0.02: return 0.6
    if cp<pl and od<-0.015: return 0.5
    if cp<pl and od>0.02: return -0.5
    return max(-0.3, min(0.3, od*5))


# Best per-coin configs
CONFIGS = {
    "WIFUSDT": {"lev":20,"mp":1.0,"mom":168,"tp":40,"sl":5,"hold":72},
    "PEPEUSDT": {"lev":20,"mp":0.5,"mom":72,"tp":200,"sl":5,"hold":72},
    "NEARUSDT": {"lev":20,"mp":0.5,"mom":168,"tp":150,"sl":5,"hold":48},
    "ARBUSDT": {"lev":20,"mp":0.5,"mom":168,"tp":150,"sl":5,"hold":72},
    "SOLUSDT": {"lev":20,"mp":0.5,"mom":168,"tp":150,"sl":5,"hold":48},
    "AVAXUSDT": {"lev":20,"mp":0.5,"mom":24,"tp":150,"sl":5,"hold":72},
    "DOTUSDT": {"lev":20,"mp":0.5,"mom":24,"tp":100,"sl":5,"hold":72},
    "MATICUSDT": {"lev":20,"mp":0.25,"mom":24,"tp":200,"sl":5,"hold":48},
    "ETHUSDT": {"lev":20,"mp":0.5,"mom":168,"tp":150,"sl":5,"hold":48},
    "BTCUSDT": {"lev":15,"mp":0.5,"mom":168,"tp":100,"sl":5,"hold":48},
    "XRPUSDT": {"lev":15,"mp":0.5,"mom":168,"tp":100,"sl":5,"hold":48},
}

def run(sym, c, h, l, v, oi, e20, e50, btc_c, cfg, cost_rt, slip_bps=0, lev_override=0, mp_override=0, tp_override=0, sl_override=0, alpha=True):
    n=len(c); lev=lev_override or cfg["lev"]; mp=mp_override or cfg["mp"]
    mom_p=cfg["mom"]; tp_roe=tp_override or cfg["tp"]; sl_roe=sl_override or cfg["sl"]
    max_hold=cfg["hold"]
    margin=EQUITY*mp; notional=margin*lev; fee=notional*cost_rt
    slip_cost=notional*slip_bps/10000
    trades=[]; pos=None; cd=0

    for i in range(max(720, mom_p+1), n):
        if pos is not None:
            pc=(c[i]/pos["bp"]-1) if pos["sd"]=="long" else -(c[i]/pos["bp"]-1)
            roe=pc*100*pos["lv"]; hh=i-pos["ei"]
            fd=pos["not"]*0.0001*(hh//8)
            sr=pos["sr"]; f=0.5 if pos.get("sc") else 1.0; m_=pos["m"]
            if not pos.get("sc") and roe>=sr:
                trades.append(m_*0.5*(sr/100)-pos["fee"]*0.5-fd*0.5-pos["slip"]*0.5)
                pos["sc"]=True; pos["sr"]=max(sr*0.1,0); continue
            if roe<=-sr:
                trades.append(m_*f*(-sr/100)-pos["fee"]*f-fd*f-pos["slip"]*f); pos=None; cd=i+6; continue
            osr=pos.get("osr",sr)
            if roe>=osr*(tp_roe/sl_roe):
                trades.append(m_*f*(osr*(tp_roe/sl_roe)/100)-pos["fee"]*f-fd*f-pos["slip"]*f); pos=None; cd=i+1; continue
            if hh>=max_hold:
                trades.append(m_*f*(roe/100)-pos["fee"]*f-fd*f-pos["slip"]*f); pos=None; continue
            continue
        if i<cd: continue
        if sym!="BTCUSDT" and i<len(btc_c) and i>=168:
            bm=(btc_c[i]-btc_c[i-168])/btc_c[i-168] if btc_c[i-168]>0 else 0
            if bm<-0.02: continue
        if e20[i]<=e50[i]: continue
        if i<mom_p: continue
        mom=(c[i]-c[i-mom_p])/c[i-mom_p]
        if mom<0.03: continue
        # OI filter
        oid=oi_div_at(oi,c,i) if oi else 0
        if oid<-0.4: continue
        # VWAP size adjustment
        sm=1.0
        if v:
            vw=vwap_at(h,l,c,v,i,96); at=atr_at(h,l,c,i)
            vd=(c[i]-vw)/at if at>0 else 0
            if vd<-0.5: sm*=1.1
            if vd>2.5: sm*=0.7
        if oid>0.4: sm*=1.15
        sm=min(sm,1.5)
        am=margin*sm; an=am*lev; af=an*cost_rt; aslip=an*slip_bps/10000
        pos={"bp":c[i],"sd":"long","ei":i,"sr":sl_roe,"osr":sl_roe,"lv":lev,
             "not":an,"m":am,"fee":af,"slip":aslip}
        continue

    # Alpha
    if alpha:
        apos=None; acd=0
        for i in range(max(720,mom_p+1),n):
            if apos is not None:
                pc=(c[i]/apos["bp"]-1) if apos["sd"]=="long" else -(c[i]/apos["bp"]-1)
                roe=pc*100*5; hh=i-apos["ei"]
                am=EQUITY*0.3; an=am*5; af=an*cost_rt; aslip=an*slip_bps/10000; fd=an*0.0001*(hh//8)
                if roe<=-8: trades.append(am*(-8/100)-af-fd-aslip); apos=None; acd=i+12; continue
                if roe>=20: trades.append(am*(20/100)-af-fd-aslip); apos=None; acd=i+4; continue
                if hh>=24: trades.append(am*(roe/100)-af-fd-aslip); apos=None; continue
                continue
            if i<acd: continue
            if e20[i]>e50[i] and i>=mom_p and (c[i]-c[i-mom_p])/c[i-mom_p]>=0.03: continue
            oid=oi_div_at(oi,c,i) if oi else 0; adx_=adx_at(h,l,c,i)
            if adx_<18 and v:
                vw=vwap_at(h,l,c,v,i,96); at=atr_at(h,l,c,i)
                vd=(c[i]-vw)/at if at>0 else 0
                if abs(vd)>=2.0 and abs(oid)<0.3:
                    apos={"bp":c[i],"sd":"short" if vd>0 else "long","ei":i}; acd=i+8; continue
            if oid>0.5 and adx_>=20 and i>=24:
                m3=(c[i]-c[i-24])/c[i-24] if c[i-24]>0 else 0
                if m3>0.01: apos={"bp":c[i],"sd":"long","ei":i}; acd=i+8; continue
    return trades

def mc(trades, eq=75, ns=2000):
    if len(trades)<10: return 100,100,0
    pnls=trades; rc=0; dds=[]; fins=[]
    for _ in range(ns):
        sh=random.sample(pnls,len(pnls)); e=eq; pk=eq; mdd=0
        for p in sh:
            e+=p; pk=max(pk,e); dd=(pk-e)/pk if pk>0 else 0; mdd=max(mdd,dd)
            if e<=0: rc+=1; break
        dds.append(mdd*100); fins.append(e)
    return round(rc/ns*100,2), round(statistics.median(dds),1), round(statistics.mean(fins),2)

def wf4(trades):
    if len(trades)<12: return 0
    fs=len(trades)//4
    return sum(1 for i in range(4) if sum(trades[i*fs:(i+1)*fs if i<3 else len(trades)])>0)

def main():
    btc_c=[b["close_price"] for b in json.load(open(dd/"BTCUSDT"/"1h.json"))]
    sym_data={}
    for sym in CONFIGS:
        p1h=dd/sym/"1h.json"
        if not p1h.exists(): continue
        b1=json.load(open(p1h))
        if len(b1)<5000: continue
        c=[b["close_price"] for b in b1]; h=[b["high_price"] for b in b1]
        l=[b["low_price"] for b in b1]; v=[b.get("base_volume",b.get("quote_volume",0)) for b in b1]
        e20=ema_arr(c,20); e50=ema_arr(c,50)
        oip=dd/sym/"oi_1h.json"
        if oip.exists():
            oir=json.load(open(oip))
            oim={int(r["timestamp"]):float(r["open_interest"]) for r in oir}
            bt=[int(b.get("open_time",0)) for b in b1]; oia=[]; last=list(oim.values())[0] if oim else 0
            for t in bt:
                near=min(oim.keys(),key=lambda k:abs(k-t),default=None) if oim else None
                if near and abs(near-t)<7200000: last=oim[near]
                oia.append(last)
        else: oia=[]
        sym_data[sym]=(c,h,l,v,oia,e20,e50)
    print(f"Loaded {len(sym_data)} symbols\n")

    def run_all(cost_rt=0.0012, slip=0, lev_o=0, mp_o=0, tp_o=0, sl_o=0, alpha=True):
        at=[]
        for sym,(c,h,l,v,oi,e20,e50) in sym_data.items():
            at.extend(run(sym,c,h,l,v,oi,e20,e50,btc_c,CONFIGS[sym],cost_rt,slip,lev_o,mp_o,tp_o,sl_o,alpha))
        return at

    # ══════════════════════════════════════════
    # 1. LEVERAGE GRID (ruin reduction)
    # ══════════════════════════════════════════
    print(f"{'='*100}")
    print(f"{'1. LEVERAGE GRID — find ruin < 5%':^100}")
    print(f"{'='*100}")
    print(f"{'Lev':>4} {'N':>5} {'WR%':>6} {'PnL$':>9} {'EV/t$':>7} {'PF':>5} {'WF':>3} {'Ruin%':>6} {'MDD%':>5} {'Final$':>8}")
    print("-"*70)
    for lev in [5, 7, 10, 12, 15, 18, 20]:
        ts=run_all(lev_o=lev)
        nt=len(ts); pnl=sum(ts); gp=sum(t for t in ts if t>0); gl=abs(sum(t for t in ts if t<=0))
        wr=sum(1 for t in ts if t>0)/max(nt,1); pf=gp/max(gl,0.01); ev=pnl/max(nt,1)
        ruin,mdd,final=mc(ts)
        wf_=wf4(ts)
        print(f"{lev:>4} {nt:>5} {wr*100:>6.1f} {pnl:>+9.1f} {ev:>+7.3f} {pf:>5.2f} {wf_:>3}/4 {ruin:>6.1f} {mdd:>5.1f} {final:>8.0f}")

    # ══════════════════════════════════════════
    # 2. MARGIN GRID
    # ══════════════════════════════════════════
    print(f"\n{'='*100}")
    print(f"{'2. MARGIN % GRID':^100}")
    print(f"{'='*100}")
    print(f"{'MP':>5} {'N':>5} {'WR%':>6} {'PnL$':>9} {'PF':>5} {'Ruin%':>6} {'MDD%':>5}")
    print("-"*50)
    for mp in [0.15, 0.25, 0.35, 0.50, 0.75, 1.0]:
        ts=run_all(mp_o=mp)
        nt=len(ts); pnl=sum(ts); gp=sum(t for t in ts if t>0); gl=abs(sum(t for t in ts if t<=0))
        wr=sum(1 for t in ts if t>0)/max(nt,1); pf=gp/max(gl,0.01)
        ruin,mdd,_=mc(ts)
        print(f"{mp:>5.2f} {nt:>5} {wr*100:>6.1f} {pnl:>+9.1f} {pf:>5.2f} {ruin:>6.1f} {mdd:>5.1f}")

    # ══════════════════════════════════════════
    # 3. COST STRESS
    # ══════════════════════════════════════════
    print(f"\n{'='*100}")
    print(f"{'3. COST STRESS TEST':^100}")
    print(f"{'='*100}")
    print(f"{'Cost':>6} {'N':>5} {'WR%':>6} {'PnL$':>9} {'PF':>5} {'Ruin%':>6}")
    print("-"*45)
    for cost_bps in [0, 5, 10, 12, 18, 24, 34, 44]:
        ts=run_all(cost_rt=cost_bps/10000)
        nt=len(ts); pnl=sum(ts); gp=sum(t for t in ts if t>0); gl=abs(sum(t for t in ts if t<=0))
        wr=sum(1 for t in ts if t>0)/max(nt,1); pf=gp/max(gl,0.01)
        ruin,_,_=mc(ts)
        marker=" ← current" if cost_bps==12 else ""
        print(f"{cost_bps:>4}bp {nt:>5} {wr*100:>6.1f} {pnl:>+9.1f} {pf:>5.2f} {ruin:>6.1f}{marker}")

    # ══════════════════════════════════════════
    # 4. SLIPPAGE STRESS
    # ══════════════════════════════════════════
    print(f"\n{'='*100}")
    print(f"{'4. SLIPPAGE STRESS TEST':^100}")
    print(f"{'='*100}")
    print(f"{'Slip':>6} {'N':>5} {'WR%':>6} {'PnL$':>9} {'PF':>5} {'Ruin%':>6}")
    print("-"*45)
    for slip in [0, 3, 5, 8, 10, 15, 20]:
        ts=run_all(slip=slip)
        nt=len(ts); pnl=sum(ts); gp=sum(t for t in ts if t>0); gl=abs(sum(t for t in ts if t<=0))
        wr=sum(1 for t in ts if t>0)/max(nt,1); pf=gp/max(gl,0.01)
        ruin,_,_=mc(ts)
        print(f"{slip:>4}bp {nt:>5} {wr*100:>6.1f} {pnl:>+9.1f} {pf:>5.2f} {ruin:>6.1f}")

    # ══════════════════════════════════════════
    # 5. TP/SL SENSITIVITY
    # ══════════════════════════════════════════
    print(f"\n{'='*100}")
    print(f"{'5. TP/SL SENSITIVITY (relative to each coin default)':^100}")
    print(f"{'='*100}")
    print(f"{'TP%':>5} {'SL%':>5} {'N':>5} {'WR%':>6} {'PnL$':>9} {'PF':>5} {'Ruin%':>6}")
    print("-"*50)
    # Test TP/SL multipliers on top of per-coin defaults
    for tp_mult, sl_mult in [(0.7,1.0),(0.85,1.0),(1.0,1.0),(1.15,1.0),(1.3,1.0),
                              (1.0,0.6),(1.0,0.8),(1.0,1.2),(1.0,1.5)]:
        all_ts=[]
        for sym,(c,h,l,v,oi,e20,e50) in sym_data.items():
            cfg=CONFIGS[sym]
            tp_=int(cfg["tp"]*tp_mult); sl_=max(2,int(cfg["sl"]*sl_mult))
            all_ts.extend(run(sym,c,h,l,v,oi,e20,e50,btc_c,cfg,0.0012,0,0,0,tp_,sl_))
        nt=len(all_ts); pnl=sum(all_ts)
        gp=sum(t for t in all_ts if t>0); gl=abs(sum(t for t in all_ts if t<=0))
        wr=sum(1 for t in all_ts if t>0)/max(nt,1); pf=gp/max(gl,0.01)
        ruin,_,_=mc(all_ts)
        marker=" ← default" if tp_mult==1.0 and sl_mult==1.0 else ""
        print(f"{tp_mult:>5.2f} {sl_mult:>5.2f} {nt:>5} {wr*100:>6.1f} {pnl:>+9.1f} {pf:>5.2f} {ruin:>6.1f}{marker}")

    # ══════════════════════════════════════════
    # 6. BEST COMBO: reduced lev + alpha
    # ══════════════════════════════════════════
    print(f"\n{'='*100}")
    print(f"{'6. RECOMMENDED SETTINGS (ruin < 5%)':^100}")
    print(f"{'='*100}")
    for lev in [10, 12, 15]:
        for mp in [0.25, 0.35, 0.50]:
            ts=run_all(lev_o=lev, mp_o=mp)
            nt=len(ts); pnl=sum(ts)
            gp=sum(t for t in ts if t>0); gl=abs(sum(t for t in ts if t<=0))
            wr=sum(1 for t in ts if t>0)/max(nt,1); pf=gp/max(gl,0.01); ev=pnl/max(nt,1)
            ruin,mdd,final=mc(ts); wf_=wf4(ts)
            safe="SAFE" if ruin<=5 else "RISKY" if ruin<=10 else "DANGER"
            print(f"  lev={lev:>2} mp={mp:.2f} | N={nt:>5} WR={wr*100:.1f}% PnL=${pnl:>+8.0f} PF={pf:.2f} WF={wf_}/4 ruin={ruin:.1f}% MDD={mdd:.0f}% final=${final:.0f} [{safe}]")

    print("\nDone!")

if __name__ == "__main__":
    main()
