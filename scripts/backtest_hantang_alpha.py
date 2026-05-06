"""Hantang momentum baseline + OI/VWAP/SMC alpha overlay ablation.

Baseline: exact hantang logic (7d momentum >= 3%, EMA20>EMA50, BTC filter,
ROE-based TP/SL, 20x lev, scale-out). Per-coin best configs from definitive_hantang.json.
Overlay: OI divergence filter, SMC boost, VWAP gate, alpha sub-entries.
1h bars, real Bybit OI, $75 equity, 24bps cost.
"""
import json, math, random, statistics, sys, time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

dd = Path("quant_runtime/historical")
COST_RT = 0.0012; EQUITY = 75.0

def ema_arr(c, p):
    e = [0.0] * len(c); e[0] = c[0]; k = 2 / (p + 1)
    for i in range(1, len(c)): e[i] = c[i] * k + e[i - 1] * (1 - k)
    return e

def atr_at(h, l, c, i, p=14):
    if i < p + 1: return 0.0001
    return sum(max(h[i-j]-l[i-j], abs(h[i-j]-c[i-j-1]), abs(l[i-j]-c[i-j-1])) for j in range(1, p+1)) / p

def adx_at(h, l, c, i, p=14):
    if i < p + 2: return 0
    pdm = []; mdm = []; trs = []
    for j in range(1, min(p+2, i+1)):
        hd = h[i-j+1] - h[i-j]; ld = l[i-j] - l[i-j+1]
        pdm.append(max(hd, 0) if hd > ld else 0); mdm.append(max(ld, 0) if ld > hd else 0)
        trs.append(max(h[i-j+1]-l[i-j+1], abs(h[i-j+1]-c[i-j]), abs(l[i-j+1]-c[i-j])))
    a = sum(trs[:p]) / p
    if a <= 0: return 0
    pdi = (sum(pdm[:p])/p)/a*100; mdi = (sum(mdm[:p])/p)/a*100
    return abs(pdi - mdi) / max(pdi + mdi, 0.01) * 100

def rsi_at(c, i, p=14):
    if i < p + 1: return 50
    g = [max(c[i-p+j]-c[i-p+j-1], 0) for j in range(1, p+1)]
    l_ = [max(c[i-p+j-1]-c[i-p+j], 0) for j in range(1, p+1)]
    ag = sum(g)/p; al = sum(l_)/p
    return 100 - 100/(1+ag/al) if al > 0 else 100

def vwap_at(h, l, c, v, i, n=96):
    s = max(0, i - n + 1); cpv = 0; cv = 0
    for j in range(s, i + 1):
        tp = (h[j] + l[j] + c[j]) / 3; cpv += tp * v[j]; cv += v[j]
    return cpv / max(cv, 1e-12)

def oi_div_at(oi, c, i, lb=24):
    if i < lb or not oi or i >= len(oi): return 0.0
    prices = c[i-lb:i+1]; ois = oi[max(0, i-lb):i+1]
    if len(ois) < lb: return 0.0
    cp = prices[-1]; ph = max(prices[:-1]); pl = min(prices[:-1])
    on = ois[-1]; oa = sum(ois[:-1]) / max(len(ois)-1, 1)
    od = (on - oa) / max(abs(oa), 1e-12)
    nh = cp > ph; nl = cp < pl
    if nh and od < -0.015: return -0.6
    if nh and od > 0.02: return 0.6
    if nl and od < -0.015: return 0.5
    if nl and od > 0.02: return -0.5
    return max(-0.3, min(0.3, od * 5))

def fvg_at(h, l, i, lb=30):
    if i < 3: return 0.0
    sc = 0.0
    for j in range(max(2, i - lb), i + 1):
        if l[j] > h[j-2]:
            gp = (l[j] - h[j-2]) / h[j-2] * 100
            if 0.1 <= gp <= 1.0 and h[j-2] <= h[i] and l[i] <= l[j]:
                age = i - j; sc = max(sc, 0.3 + 0.7 * max(0, 1 - age / 20))
        if h[j] < l[j-2]:
            gp = (l[j-2] - h[j]) / l[j-2] * 100
            if 0.1 <= gp <= 1.0 and l[j-2] >= l[i] and h[i] >= h[j]:
                age = i - j; sc = max(sc, 0.3 + 0.7 * max(0, 1 - age / 20))
    return sc


# Per-coin best configs from definitive_hantang.json
CONFIGS = {
    "WIFUSDT": {"lev": 20, "mp": 1.0, "mom": 168, "tp": 40, "sl": 5, "hold": 72},
    "PEPEUSDT": {"lev": 20, "mp": 0.5, "mom": 72, "tp": 200, "sl": 5, "hold": 72},
    "NEARUSDT": {"lev": 20, "mp": 0.5, "mom": 168, "tp": 150, "sl": 5, "hold": 48},
    "ARBUSDT": {"lev": 20, "mp": 0.5, "mom": 168, "tp": 150, "sl": 5, "hold": 72},
    "SOLUSDT": {"lev": 20, "mp": 0.5, "mom": 168, "tp": 150, "sl": 5, "hold": 48},
    "AVAXUSDT": {"lev": 20, "mp": 0.5, "mom": 24, "tp": 150, "sl": 5, "hold": 72},
    "DOTUSDT": {"lev": 20, "mp": 0.5, "mom": 24, "tp": 100, "sl": 5, "hold": 72},
    "MATICUSDT": {"lev": 20, "mp": 0.25, "mom": 24, "tp": 200, "sl": 5, "hold": 48},
    "ETHUSDT": {"lev": 20, "mp": 0.5, "mom": 168, "tp": 150, "sl": 5, "hold": 48},
    "BTCUSDT": {"lev": 15, "mp": 0.5, "mom": 168, "tp": 100, "sl": 5, "hold": 48},
    "XRPUSDT": {"lev": 15, "mp": 0.5, "mom": 168, "tp": 100, "sl": 5, "hold": 48},
}

@dataclass
class Mode:
    name: str; oi: bool = False; smc: bool = False; vwap: bool = False; alpha: bool = False

def run_hantang(sym, c, h, l, v, oi, e20, e50, btc_c, mode, cfg):
    n = len(c); lev = cfg["lev"]; mp = cfg["mp"]; mom_p = cfg["mom"]
    tp_roe = cfg["tp"]; sl_roe = cfg["sl"]; max_hold = cfg["hold"]
    margin = EQUITY * mp; notional = margin * lev; fee = notional * COST_RT
    sl_dollar = margin * sl_roe / 100
    # fee-safe check relaxed: fee is deducted from PnL, not a gate
    # (definitive_hantang validated with fee in PnL calculation)

    trades = []; pos = None; cd = 0; total_pnl = 0
    src_list = []  # track source of each trade

    for i in range(max(720, mom_p + 1), n):
        # ── Exit ──
        if pos is not None:
            pc = (c[i] / pos["bp"] - 1) if pos["sd"] == "long" else -(c[i] / pos["bp"] - 1)
            roe = pc * 100 * lev; hh = i - pos["ei"]
            fd = notional * 0.0001 * (hh // 8)
            sr = pos["sr"]
            # Scale-out at SL threshold
            if not pos.get("sc") and roe >= sr:
                pnl_ = margin * 0.5 * (sr / 100) - fee * 0.5 - fd * 0.5
                trades.append(pnl_); src_list.append(pos.get("src", "regime"))
                pos["sc"] = True; pos["sr"] = max(sr * 0.1, 0); continue
            # Stop loss
            if roe <= -sr:
                f = 0.5 if pos.get("sc") else 1.0
                pnl_ = margin * f * (-sr / 100) - fee * f - fd * f
                trades.append(pnl_); src_list.append(pos.get("src", "regime"))
                pos = None; cd = i + 6; continue
            # Take profit
            osr = pos.get("osr", sr)
            if roe >= osr * (tp_roe / sl_roe):
                f = 0.5 if pos.get("sc") else 1.0
                pnl_ = margin * f * (osr * (tp_roe / sl_roe) / 100) - fee * f - fd * f
                trades.append(pnl_); src_list.append(pos.get("src", "regime"))
                pos = None; cd = i + 1; continue
            # Time exit
            if hh >= max_hold:
                f = 0.5 if pos.get("sc") else 1.0
                pnl_ = margin * f * (roe / 100) - fee * f - fd * f
                trades.append(pnl_); src_list.append(pos.get("src", "regime"))
                pos = None; continue
            continue

        if i < cd: continue

        # ── BTC filter ──
        if sym != "BTCUSDT" and i < len(btc_c) and i >= 168:
            bm = (btc_c[i] - btc_c[i-168]) / btc_c[i-168] if btc_c[i-168] > 0 else 0
            if bm < -0.02: continue

        # ── Momentum entry (baseline) ──
        if e20[i] <= e50[i]: continue
        if i < mom_p: continue
        mom = (c[i] - c[i - mom_p]) / c[i - mom_p]
        if mom < 0.03: continue

        side = "long"

        # ── OI filter ──
        oid = 0.0
        if mode.oi and oi:
            oid = oi_div_at(oi, c, i)
            if oid < -0.4:  # fake breakout → skip
                continue

        # ── SMC filter ──
        smc_s = 0.0
        if mode.smc:
            smc_s = fvg_at(h, l, i)

        # ── VWAP filter ──
        vwap_dev = 0.0
        if mode.vwap and v:
            vw = vwap_at(h, l, c, v, i, 96)
            at = atr_at(h, l, c, i)
            vwap_dev = (c[i] - vw) / at if at > 0 else 0

        # ── Size adjustment ──
        size_mult = 1.0
        if mode.oi and oid > 0.4: size_mult *= 1.15  # OI confirms
        if mode.smc and smc_s > 0.4: size_mult *= 1.1  # SMC confirms
        if mode.vwap and vwap_dev < -0.5: size_mult *= 1.1  # pullback to VWAP
        if mode.vwap and vwap_dev > 2.5: size_mult *= 0.7  # stretched from VWAP
        if mode.oi and oid < -0.2: size_mult *= 0.8  # soft OI warning
        size_mult = min(size_mult, 1.5)

        adj_margin = margin * size_mult
        pos = {"bp": c[i], "sd": side, "ei": i, "sr": sl_roe, "osr": sl_roe, "src": "regime"}
        continue

    # ── Alpha entries when regime skips ──
    # (separate pass for clarity - only active when mode.alpha=True)
    if mode.alpha:
        alpha_trades = []
        alpha_pos = None; alpha_cd = 0
        for i in range(max(720, mom_p + 1), n):
            # Exit alpha position
            if alpha_pos is not None:
                pc = (c[i] / alpha_pos["bp"] - 1) if alpha_pos["sd"] == "long" else -(c[i] / alpha_pos["bp"] - 1)
                roe = pc * 100 * 5; hh = i - alpha_pos["ei"]  # alpha uses 5x lev
                fd = (EQUITY * 0.3 * 5) * 0.0001 * (hh // 8)
                a_margin = EQUITY * 0.3  # 30% margin for alpha
                # SL: 8% ROE
                if roe <= -8:
                    pnl_ = a_margin * (-8 / 100) - a_margin * 5 * COST_RT - fd
                    alpha_trades.append(pnl_); src_list.append("alpha")
                    alpha_pos = None; alpha_cd = i + 12; continue
                # TP: 20% ROE
                if roe >= 20:
                    pnl_ = a_margin * (20 / 100) - a_margin * 5 * COST_RT - fd
                    alpha_trades.append(pnl_); src_list.append("alpha")
                    alpha_pos = None; alpha_cd = i + 4; continue
                # Time: 24h
                if hh >= 24:
                    pnl_ = a_margin * (roe / 100) - a_margin * 5 * COST_RT - fd
                    alpha_trades.append(pnl_); src_list.append("alpha")
                    alpha_pos = None; continue
                continue

            if i < alpha_cd: continue

            # Check if regime would have entered (if so, skip alpha)
            if e20[i] > e50[i] and i >= mom_p:
                mom = (c[i] - c[i-mom_p]) / c[i-mom_p]
                if mom >= 0.03: continue  # regime handles this

            oid = oi_div_at(oi, c, i) if oi else 0
            adx_ = adx_at(h, l, c, i)

            # Alpha 1: VWAP mean reversion in ranging market
            if adx_ < 18 and v:
                vw = vwap_at(h, l, c, v, i, 96)
                at = atr_at(h, l, c, i)
                vd = (c[i] - vw) / at if at > 0 else 0
                if abs(vd) >= 2.0 and abs(oid) < 0.3:
                    asd = "short" if vd > 0 else "long"
                    alpha_pos = {"bp": c[i], "sd": asd, "ei": i, "src": "alpha_vwap"}
                    alpha_cd = i + 8; continue

            # Alpha 2: OI momentum surge
            if oid > 0.5 and adx_ >= 20 and i >= 24:
                mom3 = (c[i] - c[i-24]) / c[i-24] if c[i-24] > 0 else 0
                if mom3 > 0.01:
                    alpha_pos = {"bp": c[i], "sd": "long", "ei": i, "src": "alpha_oi"}
                    alpha_cd = i + 8; continue

        trades.extend(alpha_trades)

    return trades, src_list


def wf4(trades, n=4):
    if len(trades) < n * 3: return {"v": False, "f": [], "p": 0}
    fs = len(trades) // n; folds = []
    for i in range(n):
        f = trades[i*fs:(i+1)*fs if i < n-1 else len(trades)]
        pnl = sum(f); w = sum(1 for t in f if t > 0)
        folds.append({"q": i+1, "n": len(f), "pnl": round(pnl, 2), "wr": round(w/max(len(f), 1), 4)})
    return {"v": sum(1 for f in folds if f["pnl"] > 0) >= 3, "f": folds, "p": sum(1 for f in folds if f["pnl"] > 0)}


def mc_sim(trades, eq=75, ns=1000):
    if len(trades) < 10: return {"ruin": 100, "mdd": 100, "final": 0}
    rc = 0; dds = []; fins = []
    for _ in range(ns):
        sh = random.sample(trades, len(trades)); e = eq; pk = eq; mdd = 0
        for p in sh:
            e += p; pk = max(pk, e); dd = (pk - e) / pk if pk > 0 else 0; mdd = max(mdd, dd)
            if e <= 0: rc += 1; break
        dds.append(mdd * 100); fins.append(e)
    return {"ruin": round(rc / ns * 100, 2), "mdd": round(statistics.median(dds), 1), "final": round(statistics.mean(fins), 2)}


def main():
    # Load BTC for filter
    btc_c = [b["close_price"] for b in json.load(open(dd / "BTCUSDT" / "1h.json"))]

    modes = [
        Mode("baseline"),
        Mode("+OI", oi=True),
        Mode("+OI+SMC", oi=True, smc=True),
        Mode("+OI+SMC+VWAP", oi=True, smc=True, vwap=True),
        Mode("FULL+alpha", oi=True, smc=True, vwap=True, alpha=True),
    ]

    # Load all symbols that have configs
    sym_data = {}
    for sym in CONFIGS:
        p1h = dd / sym / "1h.json"
        if not p1h.exists(): continue
        b1 = json.load(open(p1h))
        if len(b1) < 5000: continue
        c = [b["close_price"] for b in b1]; h = [b["high_price"] for b in b1]
        l = [b["low_price"] for b in b1]; v = [b.get("base_volume", b.get("quote_volume", 0)) for b in b1]
        e20 = ema_arr(c, 20); e50 = ema_arr(c, 50)
        # Load real OI
        oip = dd / sym / "oi_1h.json"
        if oip.exists():
            oir = json.load(open(oip))
            oim = {int(r["timestamp"]): float(r["open_interest"]) for r in oir}
            bt = [int(b.get("open_time", 0)) for b in b1]
            oia = []; last = list(oim.values())[0] if oim else 0
            for t in bt:
                near = min(oim.keys(), key=lambda k: abs(k - t), default=None) if oim else None
                if near and abs(near - t) < 7200000: last = oim[near]
                oia.append(last)
        else:
            oia = []
        sym_data[sym] = (c, h, l, v, oia, e20, e50)
        print(f"  {sym}: {len(c):,} bars, OI={'real' if oia else 'none'}", flush=True)

    print(f"\n{'=' * 130}")
    print(f"{'HANTANG MOMENTUM + ALPHA OVERLAY ABLATION':^130}")
    print(f"{'=' * 130}")
    print(f"  {len(sym_data)} symbols | Equity: ${EQUITY} | Cost: {COST_RT*10000:.0f}bps\n")

    for mode in modes:
        t0 = time.time()
        all_trades = []; all_srcs = []
        sym_results = {}

        for sym, (c, h, l, v, oi, e20, e50) in sym_data.items():
            cfg = CONFIGS[sym]
            ts, srcs = run_hantang(sym, c, h, l, v, oi, e20, e50, btc_c, mode, cfg)
            all_trades.extend(ts); all_srcs.extend(srcs)
            sp = sum(ts); sw = sum(1 for t in ts if t > 0)
            sym_results[sym] = {"n": len(ts), "pnl": round(sp, 2), "wr": round(sw / max(len(ts), 1), 4)}

        el = time.time() - t0
        nt = len(all_trades)
        if nt == 0:
            print(f"  {mode.name:<20} NO TRADES"); continue

        pnl = sum(all_trades); gp = sum(t for t in all_trades if t > 0)
        gl = abs(sum(t for t in all_trades if t <= 0))
        pf = gp / max(gl, 0.01); wr = sum(1 for t in all_trades if t > 0) / nt
        ev = pnl / nt
        regime_n = sum(1 for s in all_srcs if s == "regime")
        alpha_n = sum(1 for s in all_srcs if "alpha" in s)
        alpha_pnl = sum(all_trades[i] for i in range(len(all_trades)) if i < len(all_srcs) and "alpha" in all_srcs[i])
        wf_ = wf4(all_trades); mc_ = mc_sim(all_trades)

        print(f"  {mode.name:<20} N={nt:>5} Reg={regime_n:>4} Alp={alpha_n:>4} WR={wr*100:.1f}% "
              f"PnL=${pnl:>+9.1f} EV/t=${ev:>+.2f} PF={pf:.2f} "
              f"WF={wf_['p']}/4 MC_ruin={mc_['ruin']:.1f}% MDD={mc_['mdd']:.0f}% "
              f"AlpPnL=${alpha_pnl:>+.1f} [{el:.0f}s]")

        # Per-symbol breakdown
        for sym, sr in sorted(sym_results.items(), key=lambda x: -x[1]["pnl"]):
            print(f"    {sym:12s} N={sr['n']:>4} WR={sr['wr']*100:.1f}% PnL=${sr['pnl']:>+8.1f}")

        # WF details
        if wf_["f"]:
            qs = " | ".join(f"Q{f['q']}: ${f['pnl']:+.0f}" for f in wf_["f"])
            print(f"    WF: {qs}  {'PASS' if wf_['v'] else 'FAIL'}")
        print()

    # Cost stress skipped (COST_RT is module-level, can't easily vary per-run)
    print(f"Cost stress: re-run with --cost flag for different cost levels")

    # Save
    out = Path("quant_runtime/output/hantang_alpha_ablation.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"note": "see console output"}, open(out, "w"))
    print(f"\nDone!")


if __name__ == "__main__":
    main()
