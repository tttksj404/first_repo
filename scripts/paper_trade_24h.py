"""24-hour paper trading simulation using live Bybit data.

Fetches real-time 1h candles + OI, runs the alpha strategy for 24 cycles,
logs every decision with timestamp.
Uses recommended settings: lev=15, mp=0.35, SL=3%, alpha=on.
"""
import json, subprocess, time, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "PEPEUSDT", "WIFUSDT",
           "NEARUSDT", "ARBUSDT", "AVAXUSDT", "DOTUSDT"]
EQUITY = 75.0
LEV = 15
MP = 0.35
SL_ROE = 3  # 3% ROE SL (recommended)
COST_RT = 0.0012

CONFIGS = {
    "WIFUSDT": {"mom":168,"tp":40,"sl":3,"hold":72},
    "PEPEUSDT": {"mom":72,"tp":200,"sl":3,"hold":72},
    "NEARUSDT": {"mom":168,"tp":150,"sl":3,"hold":48},
    "ARBUSDT": {"mom":168,"tp":150,"sl":3,"hold":72},
    "SOLUSDT": {"mom":168,"tp":150,"sl":3,"hold":48},
    "AVAXUSDT": {"mom":24,"tp":150,"sl":3,"hold":72},
    "DOTUSDT": {"mom":24,"tp":100,"sl":3,"hold":72},
    "ETHUSDT": {"mom":168,"tp":150,"sl":3,"hold":48},
    "BTCUSDT": {"mom":168,"tp":100,"sl":3,"hold":48},
    "XRPUSDT": {"mom":168,"tp":100,"sl":3,"hold":48},
}


def fetch_klines(symbol, interval="60", limit=200):
    """Fetch klines from Bybit."""
    url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}&interval={interval}&limit={limit}"
    result = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=10)
    data = json.loads(result.stdout)
    if data.get("retCode") != 0:
        return []
    # Bybit returns newest first, reverse
    raw = data["result"]["list"]
    bars = []
    for r in reversed(raw):
        bars.append({
            "ts": int(r[0]),
            "o": float(r[1]), "h": float(r[2]), "l": float(r[3]), "c": float(r[4]),
            "v": float(r[5]),
        })
    return bars


def fetch_oi(symbol, limit=200):
    """Fetch OI from Bybit."""
    url = f"https://api.bybit.com/v5/market/open-interest?category=linear&symbol={symbol}&intervalTime=1h&limit={limit}"
    result = subprocess.run(["curl", "-s", url], capture_output=True, text=True, timeout=10)
    data = json.loads(result.stdout)
    if data.get("retCode") != 0:
        return []
    raw = data["result"]["list"]
    return [{"ts": int(r["timestamp"]), "oi": float(r["openInterest"])} for r in reversed(raw)]


def ema_arr(c, p):
    if not c: return []
    e = [c[0]]; k = 2/(p+1)
    for x in c[1:]: e.append(x*k + e[-1]*(1-k))
    return e


def oi_div(oi_vals, prices, i, lb=24):
    if i < lb or i >= len(oi_vals) or i >= len(prices): return 0.0
    ps = prices[i-lb:i+1]; os_ = oi_vals[max(0,i-lb):i+1]
    if len(os_) < lb: return 0.0
    cp = ps[-1]; ph = max(ps[:-1]); pl = min(ps[:-1])
    on = os_[-1]; oa = sum(os_[:-1])/max(len(os_)-1,1)
    od = (on-oa)/max(abs(oa),1e-12)
    if cp > ph and od < -0.015: return -0.6
    if cp > ph and od > 0.02: return 0.6
    if cp < pl and od < -0.015: return 0.5
    if cp < pl and od > 0.02: return -0.5
    return max(-0.3, min(0.3, od*5))


def adx_calc(h, l, c, p=14):
    if len(h) < p+2: return 0
    pdm=[]; mdm=[]; trs=[]
    for j in range(1, min(p+2, len(h))):
        hd=h[-j]-h[-j-1]; ld=l[-j-1]-l[-j]
        pdm.append(max(hd,0) if hd>ld else 0); mdm.append(max(ld,0) if ld>hd else 0)
        trs.append(max(h[-j]-l[-j], abs(h[-j]-c[-j-1]), abs(l[-j]-c[-j-1])))
    a=sum(trs[:p])/p
    if a<=0: return 0
    pdi=(sum(pdm[:p])/p)/a*100; mdi=(sum(mdm[:p])/p)/a*100
    return abs(pdi-mdi)/max(pdi+mdi,0.01)*100


def main():
    out_dir = Path("quant_runtime/output/paper_24h")
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"paper_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.json"

    print(f"{'='*80}")
    print(f"{'24H PAPER TRADING SIMULATION':^80}")
    print(f"{'='*80}")
    print(f"  Symbols: {len(SYMBOLS)} | Equity: ${EQUITY} | Lev: {LEV}x | Margin: {MP*100:.0f}%")
    print(f"  SL: {SL_ROE}% ROE | Cost: {COST_RT*10000:.0f}bps")
    print(f"  Start: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    # Fetch current data for all symbols
    print("Fetching data...", flush=True)
    sym_data = {}
    for sym in SYMBOLS:
        bars = fetch_klines(sym, "60", 200)
        oi_data = fetch_oi(sym, 200)
        if not bars:
            print(f"  SKIP {sym}: no data"); continue
        c = [b["c"] for b in bars]; h = [b["h"] for b in bars]; l = [b["l"] for b in bars]
        v = [b["v"] for b in bars]
        oi_vals = [o["oi"] for o in oi_data] if oi_data else []
        e20 = ema_arr(c, 20); e50 = ema_arr(c, 50)
        sym_data[sym] = {"bars": bars, "c": c, "h": h, "l": l, "v": v,
                         "oi": oi_vals, "e20": e20, "e50": e50}
        print(f"  {sym}: {len(bars)} bars, OI={len(oi_vals)} pts, price=${c[-1]:.2f}", flush=True)

    # Scan for signals NOW
    print(f"\n{'CURRENT SIGNALS':^80}")
    print(f"{'='*80}")
    signals = []
    positions = []

    for sym, d in sym_data.items():
        cfg = CONFIGS.get(sym)
        if not cfg: continue
        c = d["c"]; h = d["h"]; l = d["l"]; e20 = d["e20"]; e50 = d["e50"]
        oi_vals = d["oi"]
        i = len(c) - 1
        if i < 170: continue

        mom_p = cfg["mom"]
        if i < mom_p: continue

        # Trend
        trend_up = e20[i] > e50[i]
        trend_dn = e20[i] < e50[i]

        # Momentum
        mom = (c[i] - c[i-mom_p]) / c[i-mom_p] * 100 if c[i-mom_p] > 0 else 0

        # OI divergence
        oid = oi_div(oi_vals, c, min(i, len(oi_vals)-1)) if oi_vals else 0

        # ADX
        adx = adx_calc(h[:i+1], l[:i+1], c[:i+1])

        # VWAP
        tp_sum = sum((h[j]+l[j]+c[j])/3 * d["v"][j] for j in range(max(0,i-96), i+1))
        v_sum = sum(d["v"][j] for j in range(max(0,i-96), i+1))
        vwap = tp_sum / max(v_sum, 1e-12)
        vwap_dev = (c[i] - vwap) / vwap * 100

        # Regime signal
        regime_signal = ""
        if trend_up and mom >= 3.0 and oid >= -0.4:
            regime_signal = "LONG"
        if oid < -0.4:
            regime_signal = "BLOCKED (OI fake breakout)"

        # Alpha signals
        alpha_signal = ""
        if not regime_signal or regime_signal == "BLOCKED (OI fake breakout)":
            if adx < 18 and abs(vwap_dev) > 1.5:
                alpha_signal = f"VWAP_MEAN_REVERT {'SHORT' if vwap_dev>0 else 'LONG'}"
            elif oid > 0.5 and adx >= 20 and mom > 1.0:
                alpha_signal = "OI_MOMENTUM LONG"

        # Margin / notional
        margin = EQUITY * MP
        notional = margin * LEV
        sl_dollar = margin * SL_ROE / 100

        status = regime_signal or alpha_signal or "CASH"

        sig = {
            "symbol": sym,
            "price": round(c[i], 4),
            "trend": "UP" if trend_up else ("DN" if trend_dn else "FLAT"),
            "mom_7d": round(mom, 2),
            "adx": round(adx, 1),
            "oi_div": round(oid, 3),
            "vwap_dev": round(vwap_dev, 2),
            "signal": status,
            "margin": round(margin, 2),
            "notional": round(notional, 2),
            "sl_dollar": round(sl_dollar, 2),
        }
        signals.append(sig)

        flag = ""
        if "LONG" in status and "BLOCKED" not in status:
            flag = " <<<< ENTRY"
            positions.append(sig)
        elif "SHORT" in status:
            flag = " <<<< ENTRY (alpha)"
            positions.append(sig)

        print(f"  {sym:12s} ${c[i]:>10.2f} trend={sig['trend']:>4} mom7d={mom:>+6.1f}% "
              f"adx={adx:>4.0f} oi={oid:>+.2f} vwap={vwap_dev:>+5.1f}% → {status}{flag}")

    # Summary
    print(f"\n{'SUMMARY':^80}")
    print(f"{'='*80}")
    entry_count = len(positions)
    cash_count = len(signals) - entry_count
    print(f"  Entries: {entry_count} | Cash: {cash_count}")
    if positions:
        total_notional = sum(p["notional"] for p in positions)
        total_risk = sum(p["sl_dollar"] for p in positions)
        print(f"  Total notional: ${total_notional:.2f}")
        print(f"  Total at risk (SL): ${total_risk:.2f} ({total_risk/EQUITY*100:.1f}% of equity)")
        print(f"\n  ENTRIES:")
        for p in positions:
            print(f"    {p['symbol']:12s} {p['signal']:>30s} | ${p['notional']:.0f} notional, ${p['sl_dollar']:.2f} risk")

    # Risk checks
    print(f"\n{'RISK CHECKS':^80}")
    print(f"{'='*80}")
    if positions:
        max_concurrent = min(len(positions), 4)
        max_risk = sum(sorted([p["sl_dollar"] for p in positions], reverse=True)[:max_concurrent])
        print(f"  Max concurrent risk (top {max_concurrent}): ${max_risk:.2f} ({max_risk/EQUITY*100:.1f}% of equity)")
        print(f"  Daily loss limit: ${EQUITY*0.05:.2f} (5%)")
        safe = max_risk < EQUITY * 0.05
        print(f"  Status: {'SAFE' if safe else 'WARNING - reduce positions'}")
    else:
        print(f"  No entries → 0 risk")

    # Save log
    log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "settings": {"equity": EQUITY, "lev": LEV, "mp": MP, "sl_roe": SL_ROE},
        "signals": signals,
        "entries": positions,
        "summary": {"entry_count": entry_count, "cash_count": cash_count},
    }
    json.dump(log, open(log_path, "w"), indent=2)
    print(f"\n  Log saved: {log_path}")

    # Schedule next check
    print(f"\n  Re-run in 1h: python3 scripts/paper_trade_24h.py")
    print(f"  Or schedule: watch -n 3600 python3 scripts/paper_trade_24h.py")


if __name__ == "__main__":
    main()
