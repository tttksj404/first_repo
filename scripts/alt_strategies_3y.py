"""3-year backtest: Grid bot + Spot trend following + Spot DCA+filter.

Tests 3 fundamentally different architectures on the same 1,090-day data.
All use SPOT costs (2bps Bitget spot fee), not futures 42bps.
"""
import json,math,statistics,sys,time
from collections import defaultdict
from pathlib import Path

def ema(v,p):
    if len(v)<p:return sum(v)/max(len(v),1)
    k=2/(p+1);e=sum(v[:p])/p
    for x in v[p:]:e=x*k+e*(1-k)
    return e

def sma(v,p):
    return sum(v[-p:])/p if len(v)>=p else sum(v)/max(len(v),1)

def atr_(h,l,c,p=14):
    if len(h)<2:return 0
    return sum(max(h[-i]-l[-i],abs(h[-i]-c[-i-1]),abs(l[-i]-c[-i-1])) for i in range(1,min(len(h),p+1)))/min(len(h)-1,p)


# ─── Strategy 1: Grid Bot ─────────────────────────────────────────

def grid_bot(closes, equity=75.0, grid_pct=1.0, n_grids=10, fee_pct=0.02):
    """Simulate grid trading on 1h close prices.
    Places n_grids levels, buys when price drops to level, sells when rises.
    """
    if len(closes)<100: return []
    trades=[]
    # Dynamic grid: recalculate center every 24h
    positions={}  # level -> (buy_price, qty)
    daily_pnl=0; daily_count=0; total_pnl=0
    grid_equity=equity

    for i in range(100, len(closes)):
        price=closes[i]

        # Recalculate grid levels every 24 bars (1 day)
        if i%24==0 or not positions:
            center=sma(closes[max(0,i-48):i+1],24)
            step=center*grid_pct/100
            levels=[]
            for g in range(-n_grids//2, n_grids//2+1):
                levels.append(round(center+g*step,2))
            # Place buy orders below current, sell orders above
            positions={}

        # Check each grid level
        for lvl in levels:
            key=round(lvl,2)
            if price<=lvl and key not in positions:
                # Buy at this level
                qty_usd=grid_equity/n_grids
                if qty_usd<1: continue
                fee=qty_usd*fee_pct/100
                positions[key]=(price, qty_usd, i)
            elif price>=lvl+step and key in positions:
                # Sell
                bp,qty_usd,ei=positions[key]
                sell_val=qty_usd*(price/bp)
                fee=sell_val*fee_pct/100
                pnl=sell_val-qty_usd-fee*2
                trades.append(("GRID",ei,i,bp,price,pnl,qty_usd))
                total_pnl+=pnl
                grid_equity+=pnl
                del positions[key]

    return trades


# ─── Strategy 2: Spot Trend Following (Donchian 15d) ──────────────

def spot_trend(closes, highs, lows, equity=75.0, lookback=15, fee_pct=0.02):
    """Spot-only trend following: buy on Donchian breakout, sell on breakdown.
    No leverage, no funding, no liquidation risk.
    """
    if len(closes)<lookback+50: return []
    trades=[];pos=None;eq=equity

    for i in range(lookback+50, len(closes)):
        dc_high=max(highs[i-lookback:i])
        dc_low=min(lows[i-lookback:i])
        price=closes[i]

        if pos is not None:
            # Check exit: price breaks below Donchian low
            if price<dc_low:
                sell_val=pos[2]*(price/pos[1])
                fee=sell_val*fee_pct/100
                pnl=sell_val-pos[2]-fee*2
                trades.append(("TREND",pos[3],i,pos[1],price,pnl,pos[2]))
                eq+=pnl
                pos=None
            # Time-based exit: max 30 days
            elif i-pos[3]>720:  # 30 days * 24h
                sell_val=pos[2]*(price/pos[1])
                fee=sell_val*fee_pct/100
                pnl=sell_val-pos[2]-fee*2
                trades.append(("TREND_TIME",pos[3],i,pos[1],price,pnl,pos[2]))
                eq+=pnl
                pos=None
        else:
            # Entry: price breaks above Donchian high
            if price>dc_high:
                invest=min(eq*0.5, eq)  # 50% of equity per trade
                if invest<1: continue
                fee=invest*fee_pct/100
                pos=(price, price, invest, i)  # (entry, entry, amount, bar_idx)

    # Close remaining
    if pos and len(closes)>0:
        sell_val=pos[2]*(closes[-1]/pos[1])
        fee=sell_val*fee_pct/100
        pnl=sell_val-pos[2]-fee*2
        trades.append(("TREND_END",pos[3],len(closes)-1,pos[1],closes[-1],pnl,pos[2]))

    return trades


# ─── Strategy 3: DCA + MA Filter ──────────────────────────────────

def dca_ma_filter(closes, equity=75.0, dca_interval=168, ma_period=200, fee_pct=0.02):
    """Weekly DCA but only buy when price > 200 SMA (trend filter).
    Sell all when price crosses below 200 SMA.
    """
    if len(closes)<ma_period+50: return []
    trades=[];holdings=[];eq=equity;weekly_invest=equity*0.02  # 2% weekly
    in_market=False

    for i in range(ma_period, len(closes)):
        price=closes[i]
        ma=sma(closes[max(0,i-ma_period):i+1],ma_period)

        if price>ma:
            # Above MA — accumulate
            if i%dca_interval==0 and eq>=weekly_invest:
                fee=weekly_invest*fee_pct/100
                qty=weekly_invest/price
                holdings.append((price,qty,weekly_invest))
                eq-=weekly_invest
                in_market=True
        else:
            # Below MA — sell all holdings
            if holdings:
                total_cost=sum(h[2] for h in holdings)
                total_qty=sum(h[1] for h in holdings)
                sell_val=total_qty*price
                fee=sell_val*fee_pct/100
                pnl=sell_val-total_cost-fee
                avg_entry=total_cost/total_qty if total_qty>0 else price
                trades.append(("DCA_EXIT",0,i,avg_entry,price,pnl,total_cost))
                eq+=sell_val-fee
                holdings=[]
                in_market=False

    # Close remaining
    if holdings and len(closes)>0:
        total_cost=sum(h[2] for h in holdings)
        total_qty=sum(h[1] for h in holdings)
        sell_val=total_qty*closes[-1]
        fee=sell_val*fee_pct/100
        pnl=sell_val-total_cost-fee
        avg_entry=total_cost/total_qty if total_qty>0 else closes[-1]
        trades.append(("DCA_END",0,len(closes)-1,avg_entry,closes[-1],pnl,total_cost))

    return trades


# ─── Walk-forward ──────────────────────────────────────────────────

def walk_forward(trades,n=4):
    if len(trades)<n*2:return {"v":False,"f":[],"p":0}
    s=sorted(trades,key=lambda t:t[1]);fs=len(s)//n;folds=[]
    for i in range(n):
        f=s[i*fs:(i+1)*fs if i<n-1 else len(s)]
        pnl=sum(t[5] for t in f);folds.append({"q":i+1,"n":len(f),"pnl":round(pnl,2)})
    pc=sum(1 for f in folds if f["pnl"]>0)
    return {"v":pc>=3,"f":folds,"p":pc}


# ─── Main ──────────────────────────────────────────────────────────

def main():
    dd=Path("quant_runtime/historical")
    symbols=["ETHUSDT","SOLUSDT","BTCUSDT"]
    eq=75.0

    print("="*100,flush=True)
    print("3-YEAR ALTERNATIVE STRATEGY BACKTEST (Spot-based, 2bps fee)",flush=True)
    print("="*100,flush=True)

    for sym in symbols:
        p=dd/sym/"1h.json"
        if not p.exists():print(f"  {sym}: no data");continue
        b1=json.load(open(p))
        c=[b["close_price"] for b in b1]
        h=[b["high_price"] for b in b1]
        l=[b["low_price"] for b in b1]
        days=len(c)/24
        print(f"\n{'='*80}",flush=True)
        print(f"  {sym}: {len(c):,} 1h bars ({days:.0f} days)",flush=True)
        print(f"{'='*80}",flush=True)

        # ── Strategy 1: Grid Bot ──
        print(f"\n  [1] GRID BOT (1% step, 10 grids, 0.02% fee)",flush=True)
        for grid_pct in [0.5, 1.0, 1.5, 2.0]:
            for n_grids in [5, 10, 20]:
                trades=grid_bot(c,eq,grid_pct,n_grids,0.02)
                if not trades:continue
                n=len(trades);pnl=sum(t[5] for t in trades)
                wins=sum(1 for t in trades if t[5]>0)
                wr=wins/max(n,1)
                wf=walk_forward(trades)
                if pnl>0:
                    print(f"    grid={grid_pct}% n={n_grids:2d}: {n:5d} trades, WR={wr*100:5.1f}%, PnL=${pnl:+8.2f}, WF={'V' if wf['v'] else 'F'}({wf['p']}/4)",flush=True)

        # ── Strategy 2: Spot Trend Following ──
        print(f"\n  [2] SPOT TREND FOLLOWING (Donchian breakout, 0.02% fee)",flush=True)
        for lb in [10, 15, 20, 30, 50]:
            trades=spot_trend(c,h,l,eq,lb,0.02)
            if not trades:continue
            n=len(trades);pnl=sum(t[5] for t in trades)
            wins=sum(1 for t in trades if t[5]>0)
            wr=wins/max(n,1)
            gp=sum(t[5] for t in trades if t[5]>0);gl=abs(sum(t[5] for t in trades if t[5]<=0))
            pf=gp/max(gl,0.01)
            avg_win=gp/max(wins,1);avg_loss=gl/max(n-wins,1)
            wf=walk_forward(trades)
            print(f"    lookback={lb:2d}: {n:3d} trades, WR={wr*100:5.1f}%, PnL=${pnl:+8.2f}, PF={pf:.2f}, avg_w=${avg_win:.2f}/avg_l=${avg_loss:.2f}, WF={'V' if wf['v'] else 'F'}({wf['p']}/4)",flush=True)

        # ── Strategy 3: DCA + MA Filter ──
        print(f"\n  [3] DCA + MA FILTER (weekly buy > 200 SMA, 0.02% fee)",flush=True)
        for ma in [50, 100, 200]:
            for interval in [24, 168, 336]:  # daily, weekly, biweekly
                label={24:"daily",168:"weekly",336:"biweekly"}[interval]
                trades=dca_ma_filter(c,eq,interval,ma,0.02)
                if not trades:continue
                n=len(trades);pnl=sum(t[5] for t in trades)
                wins=sum(1 for t in trades if t[5]>0)
                wr=wins/max(n,1)
                wf=walk_forward(trades)
                print(f"    MA={ma:3d} {label:8s}: {n:3d} trades, WR={wr*100:5.1f}%, PnL=${pnl:+8.2f}, WF={'V' if wf['v'] else 'F'}({wf['p']}/4)",flush=True)

    # ── Also test futures trend following at LOWER leverage for comparison ──
    print(f"\n{'='*80}",flush=True)
    print(f"  COMPARISON: Futures Trend Following (Donchian 15, varied leverage, 24bps)",flush=True)
    print(f"{'='*80}",flush=True)
    for sym in ["ETHUSDT","SOLUSDT"]:
        p=dd/sym/"1h.json"
        if not p.exists():continue
        b1=json.load(open(p))
        c=[b["close_price"] for b in b1];h=[b["high_price"] for b in b1];l=[b["low_price"] for b in b1]
        for lev in [1,3,5,10]:
            trades=[];pos=None;eq_=75.0;cd=0
            for i in range(65,len(c)):
                if pos:
                    roe=(c[i]/pos[1]-1)*100*lev if pos[0]=="long" else -(c[i]/pos[1]-1)*100*lev
                    if roe<=-10 or i-pos[3]>48:  # SL 10% ROE or 2d max
                        pnl_=pos[2]*(c[i]/pos[1]-1 if pos[0]=="long" else -(c[i]/pos[1]-1))-pos[2]*24/10000
                        trades.append((sym,pos[0],pos[3],i,"SL" if roe<=-10 else "TIME",pnl_))
                        eq_+=pnl_;pos=None;cd=i+3;continue
                    if roe>=15:  # TP 15% ROE
                        pnl_=pos[2]*(c[i]/pos[1]-1 if pos[0]=="long" else -(c[i]/pos[1]-1))-pos[2]*24/10000
                        trades.append((sym,pos[0],pos[3],i,"TP",pnl_))
                        eq_+=pnl_;pos=None;cd=i+1;continue
                    continue
                if i<cd:continue
                dc_h=max(h[max(0,i-15):i]);dc_l=min(l[max(0,i-15):i])
                at=atr_(h[:i+1],l[:i+1],c[:i+1])
                sd=""
                if c[i]>dc_h+0.1*at:sd="long"
                elif c[i]<dc_l-0.1*at:sd="short"
                if not sd:continue
                not_=eq_*0.1*lev;pos=(sd,c[i],not_,i)
            if trades:
                pnl=sum(t[5] for t in trades);n=len(trades)
                wr=sum(1 for t in trades if t[5]>0)/max(n,1)
                gp=sum(t[5] for t in trades if t[5]>0);gl=abs(sum(t[5] for t in trades if t[5]<=0))
                pf=gp/max(gl,0.01)
                wf_=walk_forward(trades)
                print(f"  {sym} lev={lev:2d}x: {n:4d} trades, WR={wr*100:5.1f}%, PnL=${pnl:+8.2f}, PF={pf:.2f}, WF={'V' if wf_['v'] else 'F'}({wf_['p']}/4)",flush=True)

    # Save summary
    print(f"\n{'='*80}",flush=True)
    print("DONE",flush=True)

if __name__=="__main__":main()
