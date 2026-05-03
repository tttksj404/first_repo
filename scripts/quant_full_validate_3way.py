#!/usr/bin/env python3
"""3-way full validation: OLD X4 (20-sym) vs S3 (top-5 X1 1.5x) vs M5 (hybrid).

For each strategy:
  - Full-year aggregate (WR/PF/PnL/maxDD)
  - Walk-forward 4-fold (time-ordered)
  - Slippage stress: 0/5/10/15/20 bps
  - Per-symbol breakdown
  - Parameter sensitivity (adjacent grid)
  - MC ruin 5000 runs at $50 equity
  - Funding cost 0.01%/8h included

Output: quant_runtime/full_validate_3way.json
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "quant_runtime" / "historical"
OUT = ROOT / "quant_runtime" / "full_validate_3way.json"

NOTIONAL = 50.0       # base notional = $50 equity × 1x lev
COST_RT = 0.0012
FUNDING_8H = 0.0001
EQUITY = 50.0

UNIVERSE_20 = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "APTUSDT", "ARBUSDT", "AVAXUSDT", "BNBUSDT",
    "DOTUSDT", "LINKUSDT", "LTCUSDT", "NEARUSDT", "OPUSDT",
    "PEPEUSDT", "SUIUSDT", "UNIUSDT", "WIFUSDT", "MATICUSDT",
]
TOP5_ALTS = ["OPUSDT", "NEARUSDT", "SUIUSDT", "ETHUSDT", "UNIUSDT"]


def load_1h(symbol: str) -> np.ndarray:
    path = HIST / symbol / "1h.json"
    raw = json.loads(path.read_text())
    return np.array(
        [
            [r["open_time"], r["open_price"], r["high_price"], r["low_price"], r["close_price"], r.get("base_volume", 0.0)]
            for r in raw
        ],
        dtype=np.float64,
    )


def compute_indicators(arr: np.ndarray):
    close = arr[:, 4]
    high = arr[:, 2]
    low = arr[:, 3]
    vol = arr[:, 5]
    delta = np.diff(close, prepend=close[0])
    up = np.maximum(delta, 0)
    dn = np.maximum(-delta, 0)
    rsi = np.zeros_like(close)
    avg_up = avg_dn = 0.0
    for i in range(1, len(close)):
        if i <= 14:
            avg_up = np.mean(up[1 : i + 1])
            avg_dn = np.mean(dn[1 : i + 1])
        else:
            avg_up = (avg_up * 13 + up[i]) / 14
            avg_dn = (avg_dn * 13 + dn[i]) / 14
        rsi[i] = 100 if avg_dn == 0 else 100 - 100 / (1 + avg_up / avg_dn)

    def ema(x, period):
        a = 2.0 / (period + 1)
        out = np.empty_like(x)
        out[0] = x[0]
        for i in range(1, len(x)):
            out[i] = a * x[i] + (1 - a) * out[i - 1]
        return out

    ema12 = ema(close, 12)
    ema26 = ema(close, 26)
    macd = ema12 - ema26
    macd_sig = ema(macd, 9)
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = ema(tr, 14)
    vol_ma = np.zeros_like(vol)
    for i in range(len(vol)):
        s = max(0, i - 20)
        vol_ma[i] = np.mean(vol[s : i + 1]) if i > 0 else vol[i]
    vol_r = np.where(vol_ma > 0, vol / vol_ma, 1.0)
    return rsi, macd, macd_sig, atr, vol_r


@dataclass
class Trade:
    symbol: str
    side: int
    entry_idx: int
    hold_hours: int
    pnl_usd: float       # at lev=1, NOTIONAL=$50
    is_x1: bool
    is_x4: bool          # rsi25/70 + vol≥1.3 + macd
    is_long: bool


def collect_trades(arr, ind, symbol: str,
                   rsi_long: float, rsi_short: float,
                   vol_min: float, tp_atr: float, sl_atr: float, hold: int,
                   idx_start: int = 0, idx_end: Optional[int] = None,
                   extra_bps: float = 0.0) -> list[Trade]:
    rsi, macd, macd_sig, atr, vol_r = ind
    close = arr[:, 4]
    high = arr[:, 2]
    low = arr[:, 3]
    if idx_end is None:
        idx_end = len(close)
    trades: list[Trade] = []
    cooldown = 0
    end = min(idx_end, len(close) - hold - 2)
    i = max(idx_start, 60)
    while i < end:
        if i < cooldown:
            i += 1
            continue
        long_sig = rsi[i] <= rsi_long and macd[i] > macd_sig[i] and vol_r[i] >= vol_min
        short_sig = rsi[i] >= rsi_short and macd[i] < macd_sig[i] and vol_r[i] >= vol_min
        if not long_sig and not short_sig:
            i += 1
            continue
        side = 1 if long_sig else -1
        # X1 tag (rsi 30/70 + macd, no vol gate)
        is_x1 = (rsi[i] <= 30 and macd[i] > macd_sig[i]) or (rsi[i] >= 70 and macd[i] < macd_sig[i])
        # X4 tag (rsi25/70 + vol≥1.3 + macd)
        is_x4 = ((rsi[i] <= 25 and macd[i] > macd_sig[i] and vol_r[i] >= 1.3) or
                 (rsi[i] >= 70 and macd[i] < macd_sig[i] and vol_r[i] >= 1.3))
        e = i + 1
        if e >= len(close):
            break
        entry_px = arr[e, 1]
        if entry_px <= 0 or atr[i] <= 0:
            i += 1
            continue
        tp_px = entry_px + side * tp_atr * atr[i]
        sl_px = entry_px - side * sl_atr * atr[i]
        exit_px = None
        exit_k = None
        for k in range(e, min(e + hold, len(close))):
            hi, lo = high[k], low[k]
            hit_sl = (lo <= sl_px) if side == 1 else (hi >= sl_px)
            hit_tp = (hi >= tp_px) if side == 1 else (lo <= tp_px)
            if hit_sl and hit_tp:
                exit_px = sl_px
                exit_k = k
                break
            if hit_tp:
                exit_px = tp_px
                exit_k = k
                break
            if hit_sl:
                exit_px = sl_px
                exit_k = k
                break
        if exit_px is None:
            exit_k = min(e + hold - 1, len(close) - 1)
            exit_px = close[exit_k]
        hold_hours = (exit_k - e) + 1
        roe = side * (exit_px - entry_px) / entry_px
        fee = NOTIONAL * (COST_RT + 2 * extra_bps / 10000.0)
        funding = NOTIONAL * FUNDING_8H * (hold_hours // 8)
        pnl = NOTIONAL * roe - fee - funding
        trades.append(Trade(symbol, side, e, hold_hours, pnl, is_x1, is_x4, side == 1))
        i = e + 1
        cooldown = i + 2
    return trades


def aggregate_stats(pnls: list[float]) -> dict:
    n = len(pnls)
    if n == 0:
        return {"n": 0, "wr": 0, "pf": None, "total": 0, "max_dd": 0,
                "avg_win": 0, "avg_loss": 0, "max_consec_loss": 0}
    wins = sum(1 for x in pnls if x > 0)
    wr = wins / n
    total = sum(pnls)
    win_sum = sum(x for x in pnls if x > 0)
    loss_abs = sum(abs(x) for x in pnls if x <= 0)
    pf = win_sum / loss_abs if loss_abs > 0 else float("inf")
    eq = np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    max_dd = (peak - eq).max()
    avg_win = win_sum / wins if wins else 0
    avg_loss = -loss_abs / (n - wins) if (n - wins) else 0
    # max consecutive losses
    max_streak = streak = 0
    for x in pnls:
        if x <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return {
        "n": n,
        "wr": round(wr, 4),
        "pf": round(pf, 3) if math.isfinite(pf) else None,
        "total": round(total, 2),
        "max_dd": round(float(max_dd), 2),
        "avg_win": round(avg_win, 3),
        "avg_loss": round(avg_loss, 3),
        "max_consec_loss": max_streak,
    }


def mc_ruin(pnls: list[float], n_runs: int = 5000) -> dict:
    arr = np.array(pnls, dtype=np.float64)
    if len(arr) == 0:
        return {"ruin_pct": 0, "median_final_eq": EQUITY}
    rng = np.random.default_rng(42)
    ruin = 0
    final_eqs = []
    for _ in range(n_runs):
        order = rng.permutation(len(arr))
        e = EQUITY
        m = e
        for j in order:
            e += arr[j]
            if e < m:
                m = e
        final_eqs.append(e)
        if m <= EQUITY * 0.5:
            ruin += 1
    return {
        "ruin_pct": round(ruin / n_runs * 100, 2),
        "median_final_eq": round(float(np.median(final_eqs)), 2),
        "p5_final_eq": round(float(np.percentile(final_eqs, 5)), 2),
    }


def apply_strategy(trades: list[Trade], strategy: str) -> list[float]:
    """Apply leverage rules per strategy and return scaled PnLs."""
    pnls: list[float] = []
    for t in trades:
        if strategy == "OLD_X4":
            # X4 single, lev 1x
            lev = 1.0
        elif strategy == "S3":
            # X1 on top-5, lev 1.5x always
            lev = 1.5
        elif strategy == "M5":
            # X1 on top-5, lev 1x default, 3x on X4 (symmetric)
            lev = 3.0 if t.is_x4 else 1.0
        else:
            lev = 1.0
        pnls.append(t.pnl_usd * lev)
    return pnls


# ===== STRATEGY DEFINITIONS =====
# OLD_X4: X4 single (rsi25/70, vol1.3, macd, tp0.5, sl3.0, hold24) on 20 symbols
# S3:     X1 (rsi30/70, vol1.0, macd, tp0.5, sl3.0, hold24) on top-5 alts
# M5:     X1 trigger same as S3 but tagged for X4 boost; on top-5 alts

STRATEGIES = {
    "OLD_X4": {
        "universe": UNIVERSE_20,
        "rsi_long": 25, "rsi_short": 70, "vol_min": 1.3,
        "tp_atr": 0.5, "sl_atr": 3.0, "hold": 24,
    },
    "S3": {
        "universe": TOP5_ALTS,
        "rsi_long": 30, "rsi_short": 70, "vol_min": 1.0,
        "tp_atr": 0.5, "sl_atr": 3.0, "hold": 24,
    },
    "M5": {
        "universe": TOP5_ALTS,
        "rsi_long": 30, "rsi_short": 70, "vol_min": 1.0,
        "tp_atr": 0.5, "sl_atr": 3.0, "hold": 24,
    },
}


def build_trades_for_strategy(name: str, data_cache: dict, idx_start: int = 0,
                               idx_end: Optional[int] = None, extra_bps: float = 0.0) -> list[Trade]:
    cfg = STRATEGIES[name]
    out: list[Trade] = []
    for s in cfg["universe"]:
        a, ind = data_cache[s]
        out.extend(collect_trades(a, ind, s,
                                  cfg["rsi_long"], cfg["rsi_short"], cfg["vol_min"],
                                  cfg["tp_atr"], cfg["sl_atr"], cfg["hold"],
                                  idx_start, idx_end, extra_bps))
    return out


def main():
    t0 = time.time()
    # Load full universe
    all_syms = sorted(set(UNIVERSE_20 + TOP5_ALTS))
    data = {}
    for s in all_syms:
        a = load_1h(s)
        ind = compute_indicators(a)
        data[s] = (a, ind)
    n_bars = len(data[all_syms[0]][0])
    print(f"Loaded {len(all_syms)} symbols × 1h × {n_bars} bars in {time.time()-t0:.1f}s")
    print()

    out: dict = {"strategies": {}, "comparison": []}

    for name in ["OLD_X4", "S3", "M5"]:
        print(f"\n===== {name} =====")
        cfg = STRATEGIES[name]
        print(f"  universe={cfg['universe']}")
        print(f"  rsi {cfg['rsi_long']}/{cfg['rsi_short']}, vol≥{cfg['vol_min']}, tp={cfg['tp_atr']} sl={cfg['sl_atr']}, hold={cfg['hold']}h")

        # ---- 1. Full-year ----
        trades_full = build_trades_for_strategy(name, data, 0, n_bars, 0.0)
        pnls_full = apply_strategy(trades_full, name)
        agg = aggregate_stats(pnls_full)
        ruin = mc_ruin(pnls_full)
        annual_pct = agg["total"] / EQUITY * 100
        print(f"  Full year: N={agg['n']} WR={agg['wr']:.3f} PF={agg['pf']} total=${agg['total']:+.2f} ({annual_pct:+.1f}%/yr) maxDD=${agg['max_dd']:.2f}")
        print(f"             ruin={ruin['ruin_pct']:.1f}%  med_final=${ruin['median_final_eq']:.2f}  p5=${ruin['p5_final_eq']:.2f}")

        # ---- 2. Walk-forward 4-fold ----
        wf_results = []
        wf_pass = 0
        fold_size = n_bars // 4
        for k in range(4):
            tr_end = (k + 1) * fold_size
            te_start = tr_end
            te_end = min(te_start + fold_size, n_bars) if k < 3 else n_bars
            # Use train for sanity, test as OOS
            te_trades = build_trades_for_strategy(name, data, te_start, te_end, 0.0)
            te_pnls = apply_strategy(te_trades, name)
            te_agg = aggregate_stats(te_pnls)
            wf_results.append({
                "fold": k, "te_n": te_agg["n"], "te_wr": te_agg["wr"],
                "te_pf": te_agg["pf"], "te_total": te_agg["total"],
            })
            if te_agg["total"] > 0:
                wf_pass += 1
        print(f"  WF 4-fold: {wf_pass}/4 folds positive  | folds: " + " ".join(f"f{r['fold']}=${r['te_total']:+.2f}(N{r['te_n']})" for r in wf_results))

        # ---- 3. Slippage stress 0/5/10/15/20 bps ----
        slip_rows = []
        for bps in [0, 5, 10, 15, 20]:
            tr = build_trades_for_strategy(name, data, 0, n_bars, float(bps))
            p = apply_strategy(tr, name)
            a = aggregate_stats(p)
            slip_rows.append({"bps": bps, "n": a["n"], "total": a["total"], "wr": a["wr"], "pf": a["pf"]})
        print(f"  Slippage:  " + "  ".join(f"{r['bps']}bps=${r['total']:+.2f}" for r in slip_rows))

        # ---- 4. Per-symbol breakdown ----
        per_sym = {}
        for s in cfg["universe"]:
            sym_trades = [t for t in trades_full if t.symbol == s]
            sym_pnls = apply_strategy(sym_trades, name)
            per_sym[s] = {"n": len(sym_pnls), "total": round(sum(sym_pnls), 2)}
        positive_syms = sum(1 for v in per_sym.values() if v["total"] > 0)
        print(f"  Per-sym:   {positive_syms}/{len(cfg['universe'])} symbols positive")
        for s, v in sorted(per_sym.items(), key=lambda kv: -kv[1]["total"])[:10]:
            print(f"             {s:>10s}  N={v['n']:>3d}  ${v['total']:+.2f}")

        # ---- 5. Parameter sensitivity (adjacent grid) ----
        # Vary rsi_long ±5, sl_atr ±0.5, hold ±12
        sens_results = []
        base_total = agg["total"]
        rsi_long_grid = [cfg["rsi_long"] - 5, cfg["rsi_long"], cfg["rsi_long"] + 5]
        sl_grid = [max(1.5, cfg["sl_atr"] - 0.5), cfg["sl_atr"], cfg["sl_atr"] + 0.5]
        hold_grid = [max(12, cfg["hold"] - 12), cfg["hold"], cfg["hold"] + 12]
        positive_neighbors = 0
        total_neighbors = 0
        for rl in rsi_long_grid:
            for sl in sl_grid:
                for h in hold_grid:
                    # build trades with modified params
                    tr2: list[Trade] = []
                    for s in cfg["universe"]:
                        a2, ind2 = data[s]
                        tr2.extend(collect_trades(a2, ind2, s,
                                                  rl, cfg["rsi_short"], cfg["vol_min"],
                                                  cfg["tp_atr"], sl, h, 0, n_bars, 0.0))
                    p2 = apply_strategy(tr2, name)
                    a2s = aggregate_stats(p2)
                    sens_results.append({"rsi_long": rl, "sl": sl, "hold": h,
                                         "n": a2s["n"], "total": a2s["total"], "wr": a2s["wr"]})
                    total_neighbors += 1
                    if a2s["total"] > 0:
                        positive_neighbors += 1
        print(f"  Sensitivity: {positive_neighbors}/{total_neighbors} neighbor configs positive  (base=${base_total:+.2f})")

        # Best/worst neighbors
        sens_sorted = sorted(sens_results, key=lambda r: -r["total"])
        print(f"             best:  rsi{sens_sorted[0]['rsi_long']} sl{sens_sorted[0]['sl']} h{sens_sorted[0]['hold']} = ${sens_sorted[0]['total']:+.2f}")
        print(f"             worst: rsi{sens_sorted[-1]['rsi_long']} sl{sens_sorted[-1]['sl']} h{sens_sorted[-1]['hold']} = ${sens_sorted[-1]['total']:+.2f}")

        out["strategies"][name] = {
            "config": cfg,
            "full_year": {**agg, "annual_pct": round(annual_pct, 1)},
            "mc_ruin": ruin,
            "walk_forward": {"pass_count": wf_pass, "folds": wf_results},
            "slippage_stress": slip_rows,
            "per_symbol": per_sym,
            "sym_diversification": f"{positive_syms}/{len(cfg['universe'])}",
            "param_sensitivity": {
                "neighbors_positive": f"{positive_neighbors}/{total_neighbors}",
                "best": sens_sorted[0],
                "worst": sens_sorted[-1],
                "grid": sens_results,
            },
        }

    # ---- Comparison table ----
    print("\n" + "=" * 100)
    print("COMPARISON TABLE")
    print("=" * 100)
    print(f"{'Metric':<30s} {'OLD_X4 (20-sym)':>22s} {'S3 (top5 1.5x)':>22s} {'M5 (hybrid)':>22s}")
    print("-" * 100)
    metrics = [
        ("Universe size", lambda d: f"{len(d['config']['universe'])}"),
        ("N trades", lambda d: f"{d['full_year']['n']}"),
        ("WR", lambda d: f"{d['full_year']['wr']:.3f}"),
        ("PF", lambda d: f"{d['full_year']['pf']}"),
        ("Total PnL ($)", lambda d: f"{d['full_year']['total']:+.2f}"),
        ("Annual return", lambda d: f"{d['full_year']['annual_pct']:+.1f}%"),
        ("Max DD ($)", lambda d: f"{d['full_year']['max_dd']:.2f}"),
        ("Max consec loss", lambda d: f"{d['full_year']['max_consec_loss']}"),
        ("MC ruin %", lambda d: f"{d['mc_ruin']['ruin_pct']:.2f}"),
        ("WF passed", lambda d: d['walk_forward']['pass_count']),
        ("Sym diversif", lambda d: d['sym_diversification']),
        ("5bps slip $", lambda d: f"{[s for s in d['slippage_stress'] if s['bps']==5][0]['total']:+.2f}"),
        ("10bps slip $", lambda d: f"{[s for s in d['slippage_stress'] if s['bps']==10][0]['total']:+.2f}"),
        ("Param robust", lambda d: d['param_sensitivity']['neighbors_positive']),
    ]
    for label, fn in metrics:
        v_old = fn(out["strategies"]["OLD_X4"])
        v_s3 = fn(out["strategies"]["S3"])
        v_m5 = fn(out["strategies"]["M5"])
        print(f"{label:<30s} {v_old!s:>22s} {v_s3!s:>22s} {v_m5!s:>22s}")

    # ---- Verdict ----
    print()
    print("=" * 100)
    print("VERDICT (gates: WF≥3/4, ruin≤5%, 10bps slip>0, sym_diversif≥40%, sens≥70%)")
    print("=" * 100)
    for name in ["OLD_X4", "S3", "M5"]:
        d = out["strategies"][name]
        wf = d["walk_forward"]["pass_count"]
        ruin = d["mc_ruin"]["ruin_pct"]
        slip10 = [s for s in d["slippage_stress"] if s["bps"] == 10][0]["total"]
        sym_pos = int(d["sym_diversification"].split("/")[0])
        sym_tot = int(d["sym_diversification"].split("/")[1])
        sym_pct = sym_pos / sym_tot if sym_tot else 0
        sens_pos, sens_tot = map(int, d["param_sensitivity"]["neighbors_positive"].split("/"))
        sens_pct = sens_pos / sens_tot if sens_tot else 0
        gates = {
            "WF≥3/4": wf >= 3,
            "ruin≤5%": ruin <= 5,
            "10bps>0": slip10 > 0,
            "diversif≥40%": sym_pct >= 0.4,
            "sens≥70%": sens_pct >= 0.7,
        }
        all_pass = all(gates.values())
        status = "✅ PASS" if all_pass else "❌ FAIL"
        print(f"  {name}: {status}  | " + " ".join(f"{k}={'✓' if v else '✗'}" for k, v in gates.items()))

    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nElapsed: {time.time()-t0:.1f}s, saved: {OUT}")


if __name__ == "__main__":
    main()
