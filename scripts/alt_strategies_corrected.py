"""Corrected 3-year backtest — fixes all identified uncertainties.

Fixes:
1. Grid bot: 0.1% Bitget spot fee (not 0.02%), fixed capital (no compounding),
   tracks unrealized inventory P&L, reports mark-to-market equity
2. Spot trend: adds slippage (0.05%), tracks equity curve
3. All: reports max drawdown on TOTAL equity (not just closed trades)
"""
import json,math,statistics,sys
from pathlib import Path

def ema(v,p):
    if len(v)<p:return sum(v)/max(len(v),1)
    k=2/(p+1);e=sum(v[:p])/p
    for x in v[p:]:e=x*k+e*(1-k)
    return e

def sma(v,p):
    return sum(v[-p:])/p if len(v)>=p else sum(v)/max(len(v),1)

# ─── Corrected Grid Bot ───────────────────────────────────────────

def grid_bot_corrected(closes, equity=75.0, grid_pct=1.0, n_grids=8,
                       fee_pct=0.1, recenter_hours=24):
    """Fixed grid bot: 0.1% fee, NO compounding, tracks inventory MTM."""
    if len(closes)<200: return {},[]

    FIXED_CAPITAL = equity  # never reinvest
    per_grid = FIXED_CAPITAL / n_grids

    inventory = {}  # level -> (buy_price, usd_amount)
    closed_trades = []
    equity_curve = []
    cash = FIXED_CAPITAL
    total_fees = 0
    levels = []

    for i in range(100, len(closes)):
        price = closes[i]

        # Recenter grid every N hours
        if i % recenter_hours == 0 or not levels:
            center = sma(closes[max(0,i-48):i+1], 24)
            step = center * grid_pct / 100
            levels = [round(center + g * step, 2) for g in range(-n_grids//2, n_grids//2+1)]
            # Don't sell existing inventory on recenter

        # Check grid levels
        for lvl in levels:
            key = round(lvl, 2)

            # BUY: price touches grid level from above, no existing position at this level
            if price <= lvl and key not in inventory:
                if cash < per_grid or per_grid < 1:
                    continue
                fee = per_grid * fee_pct / 100
                qty_coin = (per_grid - fee) / price
                inventory[key] = (price, per_grid, qty_coin, i)
                cash -= per_grid
                total_fees += fee

            # SELL: price rises above level + 1 step, have inventory at this level
            elif price >= lvl + step and key in inventory:
                bp, usd_in, qty_coin, entry_i = inventory[key]
                sell_val = qty_coin * price
                fee = sell_val * fee_pct / 100
                net = sell_val - fee
                pnl = net - usd_in
                closed_trades.append({
                    "ei": entry_i, "xi": i, "bp": bp, "sp": price,
                    "pnl": pnl, "fee": fee + usd_in * fee_pct / 100
                })
                cash += net
                total_fees += fee
                del inventory[key]

        # Mark-to-market equity
        inv_value = sum(qty * price for _, _, qty, _ in inventory.values())
        mtm_equity = cash + inv_value
        equity_curve.append(mtm_equity)

    # Final: liquidate remaining inventory at last price
    final_price = closes[-1]
    for key, (bp, usd_in, qty, ei) in list(inventory.items()):
        sell_val = qty * final_price
        fee = sell_val * fee_pct / 100
        net = sell_val - fee
        pnl = net - usd_in
        closed_trades.append({
            "ei": ei, "xi": len(closes)-1, "bp": bp, "sp": final_price,
            "pnl": pnl, "fee": fee, "forced": True
        })
        cash += net
        total_fees += fee
    inventory.clear()

    # Stats
    final_equity = cash
    peak = FIXED_CAPITAL
    max_dd = 0
    for eq in equity_curve:
        peak = max(peak, eq)
        dd = peak - eq
        max_dd = max(max_dd, dd)

    n = len(closed_trades)
    wins = sum(1 for t in closed_trades if t["pnl"] > 0)
    total_pnl = final_equity - FIXED_CAPITAL

    # Walk-forward
    wf_folds = []
    if n >= 8:
        fs = n // 4
        for fi in range(4):
            f = closed_trades[fi*fs:(fi+1)*fs if fi<3 else n]
            fp = sum(t["pnl"] for t in f)
            wf_folds.append(fp)

    return {
        "trades": n, "wins": wins, "wr": wins/max(n,1),
        "total_pnl": round(total_pnl, 2),
        "total_fees": round(total_fees, 2),
        "final_equity": round(final_equity, 2),
        "max_dd": round(max_dd, 2),
        "wf_folds": wf_folds,
        "wf_valid": sum(1 for f in wf_folds if f > 0) >= 3 if len(wf_folds) == 4 else False,
    }, equity_curve


# ─── Corrected Spot Trend Following ───────────────────────────────

def spot_trend_corrected(closes, highs, lows, equity=75.0, lookback=50,
                         fee_pct=0.1, slippage_pct=0.05):
    """Spot trend following with realistic fees + slippage."""
    if len(closes) < lookback + 100: return {}, []

    trades = []
    pos = None
    eq = equity
    equity_curve = []
    cost_pct = fee_pct + slippage_pct  # total per side

    for i in range(lookback + 50, len(closes)):
        price = closes[i]
        dc_high = max(highs[i-lookback:i])
        dc_low = min(lows[i-lookback:i])

        # Track equity
        if pos:
            current_val = pos["qty"] * price
            equity_curve.append(eq + current_val)
        else:
            equity_curve.append(eq)

        if pos is not None:
            # Exit: below Donchian low or max 30 days
            exit = price < dc_low or (i - pos["ei"]) > 720
            if exit:
                sell_price = price * (1 - cost_pct / 100)  # slippage on exit
                sell_val = pos["qty"] * sell_price
                pnl = sell_val - pos["cost"]
                trades.append({
                    "ei": pos["ei"], "xi": i,
                    "bp": pos["bp"], "sp": price,
                    "pnl": round(pnl, 4),
                    "reason": "DC_LOW" if price < dc_low else "TIME"
                })
                eq += sell_val
                pos = None
        else:
            # Entry: above Donchian high
            if price > dc_high:
                invest = eq * 0.5  # 50% position
                if invest < 1:
                    continue
                buy_price = price * (1 + cost_pct / 100)  # slippage on entry
                qty = invest / buy_price
                pos = {"bp": price, "qty": qty, "cost": invest, "ei": i}
                eq -= invest

    # Close remaining
    if pos:
        sell_val = pos["qty"] * closes[-1] * (1 - cost_pct / 100)
        pnl = sell_val - pos["cost"]
        trades.append({"ei": pos["ei"], "xi": len(closes)-1,
                       "bp": pos["bp"], "sp": closes[-1], "pnl": round(pnl, 4)})
        eq += sell_val
        pos = None

    final_equity = eq
    total_pnl = final_equity - equity
    n = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    gp = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gl = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
    pf = gp / max(gl, 0.01)

    peak = equity
    max_dd = 0
    for e in equity_curve:
        peak = max(peak, e)
        max_dd = max(max_dd, peak - e)

    wf_folds = []
    if n >= 8:
        fs = n // 4
        for fi in range(4):
            f = trades[fi*fs:(fi+1)*fs if fi < 3 else n]
            wf_folds.append(sum(t["pnl"] for t in f))

    return {
        "trades": n, "wins": wins, "wr": round(wins/max(n,1), 4),
        "total_pnl": round(total_pnl, 2), "pf": round(pf, 2),
        "final_equity": round(final_equity, 2),
        "max_dd": round(max_dd, 2),
        "avg_win": round(gp/max(wins,1), 2),
        "avg_loss": round(gl/max(n-wins,1), 2),
        "wf_folds": wf_folds,
        "wf_valid": sum(1 for f in wf_folds if f > 0) >= 3 if len(wf_folds) == 4 else False,
    }, equity_curve


# ─── Main ──────────────────────────────────────────────────────────

def main():
    dd = Path("quant_runtime/historical")
    symbols = ["ETHUSDT", "SOLUSDT", "BTCUSDT"]
    eq = 75.0

    print("=" * 110, flush=True)
    print("CORRECTED 3-YEAR BACKTEST (0.1% Bitget spot fee, fixed capital, MTM equity)", flush=True)
    print("=" * 110, flush=True)

    all_results = {}

    for sym in symbols:
        p = dd / sym / "1h.json"
        if not p.exists(): continue
        b1 = json.load(open(p))
        c = [b["close_price"] for b in b1]
        h = [b["high_price"] for b in b1]
        l = [b["low_price"] for b in b1]
        days = len(c) / 24

        print(f"\n{'='*80}", flush=True)
        print(f"  {sym}: {len(c):,} 1h bars ({days:.0f} days)", flush=True)
        print(f"{'='*80}", flush=True)

        # ── Grid Bot (corrected) ──
        print(f"\n  [GRID BOT] 0.1% fee, fixed $75, MTM equity tracking", flush=True)
        for grid_pct in [1.0, 1.5, 2.0, 3.0]:
            for n_grids in [6, 8, 10]:
                result, _ = grid_bot_corrected(c, eq, grid_pct, n_grids, fee_pct=0.1)
                if result["trades"] > 0:
                    wf_str = "V" if result["wf_valid"] else "F"
                    wf_p = sum(1 for f in result["wf_folds"] if f > 0) if result["wf_folds"] else 0
                    print(f"    grid={grid_pct}% n={n_grids:2d}: {result['trades']:5d}t "
                          f"WR={result['wr']*100:5.1f}% PnL=${result['total_pnl']:+8.2f} "
                          f"fees=${result['total_fees']:6.2f} final=${result['final_equity']:8.2f} "
                          f"maxDD=${result['max_dd']:6.2f} WF={wf_str}({wf_p}/4)", flush=True)
                    key = f"GRID_{sym}_{grid_pct}_{n_grids}"
                    all_results[key] = result

        # ── Spot Trend (corrected) ──
        print(f"\n  [SPOT TREND] 0.1% fee + 0.05% slippage, Donchian breakout", flush=True)
        for lb in [15, 20, 30, 50]:
            result, _ = spot_trend_corrected(c, h, l, eq, lb, fee_pct=0.1, slippage_pct=0.05)
            if result["trades"] > 0:
                wf_str = "V" if result["wf_valid"] else "F"
                wf_p = sum(1 for f in result["wf_folds"] if f > 0) if result["wf_folds"] else 0
                print(f"    lb={lb:2d}: {result['trades']:3d}t WR={result['wr']*100:5.1f}% "
                      f"PnL=${result['total_pnl']:+8.2f} PF={result['pf']:.2f} "
                      f"avg_w=${result['avg_win']:.2f}/avg_l=${result['avg_loss']:.2f} "
                      f"maxDD=${result['max_dd']:6.2f} WF={wf_str}({wf_p}/4)", flush=True)
                key = f"TREND_{sym}_{lb}"
                all_results[key] = result

    # ── Buy & Hold comparison ──
    print(f"\n{'='*80}", flush=True)
    print(f"  BUY & HOLD COMPARISON ($75 invested at start)", flush=True)
    print(f"{'='*80}", flush=True)
    for sym in symbols:
        p = dd / sym / "1h.json"
        if not p.exists(): continue
        b1 = json.load(open(p))
        c = [b["close_price"] for b in b1]
        start_price = c[100]
        end_price = c[-1]
        bh_return = (end_price / start_price - 1)
        bh_pnl = eq * bh_return
        # Max drawdown
        peak_p = start_price
        max_dd_pct = 0
        for p in c[100:]:
            peak_p = max(peak_p, p)
            dd_pct = (peak_p - p) / peak_p
            max_dd_pct = max(max_dd_pct, dd_pct)
        print(f"  {sym}: ${start_price:.2f} → ${end_price:.2f} ({bh_return*100:+.1f}%) "
              f"PnL=${bh_pnl:+.2f} maxDD={max_dd_pct*100:.1f}%", flush=True)

    # ── Summary ──
    print(f"\n{'='*110}", flush=True)
    print(f"SUMMARY: BEST STRATEGIES (sorted by PnL)", flush=True)
    print(f"{'='*110}", flush=True)
    sorted_results = sorted(all_results.items(), key=lambda x: x[1].get("total_pnl", 0), reverse=True)
    for i, (key, r) in enumerate(sorted_results[:15]):
        wf_str = "V" if r.get("wf_valid") else "F"
        wf_p = sum(1 for f in r.get("wf_folds", []) if f > 0) if r.get("wf_folds") else 0
        pf_str = f"PF={r['pf']:.2f}" if "pf" in r else "PF=N/A"
        print(f"  {i+1:>2}. {key:35s} {r['trades']:5d}t WR={r['wr']*100:5.1f}% "
              f"PnL=${r['total_pnl']:+8.2f} {pf_str:10s} maxDD=${r['max_dd']:6.2f} WF={wf_str}({wf_p}/4)", flush=True)

    # Save
    out = Path("quant_runtime/output/corrected_3y_results.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    sv = {k: {kk: vv for kk, vv in v.items() if kk != "equity_curve"} for k, v in all_results.items()}
    out.write_text(json.dumps(sv, indent=2))
    print(f"\nSaved to {out}", flush=True)

if __name__ == "__main__":
    main()
