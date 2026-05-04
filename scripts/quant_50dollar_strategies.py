#!/usr/bin/env python3
"""$50-자본 즉시-배포 전략 발굴.

전제:
- 자본 $50, 시간 없음 → 즉시 배포 가능해야 함
- 동시 1포지션 max → universe 작게, 신호 빈도 낮아야 함
- 슬리피지 5bps survive 필수
- MC ruin <= 10% (aggressive)

후보 전략 5개:
  S1: 최고 edge symbol 단일 — 위 심볼당 PnL 분석에서 최고 1개만
  S2: Top-5 concentrated — X1 params on top-5 symbols
  S3: ETH-only (가장 안정적 large-cap)
  S4: 변동성-주도 alts (SOL/OP/NEAR/SUI) only
  S5: 시간대 필터 — US 활성 시간만 (14-22 UTC)

각 전략에 대해:
  - 1년 백테스트 (full data)
  - OOS test 분리
  - per-trade EV
  - 슬리피지 5bps survive 여부
  - MC ruin 5000회 부트스트랩
  - $50 capital 시 연 PnL 추정

Output: quant_runtime/50dollar_strategies.json
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "quant_runtime" / "historical"
OUT = ROOT / "quant_runtime" / "50dollar_strategies.json"

NOTIONAL = 100.0
COST_RT = 0.0012
EQUITY = 50.0


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
class P:
    rsi_long: float
    rsi_short: float
    vol_min: float
    tp_atr: float
    sl_atr: float
    hold: int
    hour_filter: tuple | None = None  # (start, end) UTC hours, e.g., (14, 22) for US session


def collect_pnls(arr, ind, p: P, idx_start: int = 0, idx_end: int | None = None,
                 extra_bps: float = 0.0) -> list[float]:
    rsi, macd, macd_sig, atr, vol_r = ind
    close = arr[:, 4]
    high = arr[:, 2]
    low = arr[:, 3]
    open_time = arr[:, 0]  # ms timestamp
    fee = NOTIONAL * (COST_RT + 2 * extra_bps / 10000.0)
    if idx_end is None:
        idx_end = len(close)
    pnls: list[float] = []
    cooldown = 0
    end = min(idx_end, len(close) - p.hold - 2)
    i = max(idx_start, 60)
    while i < end:
        if i < cooldown:
            i += 1
            continue
        # Hour filter (UTC)
        if p.hour_filter is not None:
            ts_ms = open_time[i]
            hr = int((ts_ms / 1000 / 3600) % 24)
            h_start, h_end = p.hour_filter
            in_window = (h_start <= hr < h_end) if h_start < h_end else (hr >= h_start or hr < h_end)
            if not in_window:
                i += 1
                continue
        long_sig = rsi[i] <= p.rsi_long and macd[i] > macd_sig[i] and vol_r[i] >= p.vol_min
        short_sig = rsi[i] >= p.rsi_short and macd[i] < macd_sig[i] and vol_r[i] >= p.vol_min
        if not long_sig and not short_sig:
            i += 1
            continue
        side = 1 if long_sig else -1
        e = i + 1
        if e >= len(close):
            break
        entry_px = arr[e, 1]
        if entry_px <= 0 or atr[i] <= 0:
            i += 1
            continue
        tp_px = entry_px + side * p.tp_atr * atr[i]
        sl_px = entry_px - side * p.sl_atr * atr[i]
        exit_px = None
        for k in range(e, min(e + p.hold, len(close))):
            hi, lo = high[k], low[k]
            hit_sl = (lo <= sl_px) if side == 1 else (hi >= sl_px)
            hit_tp = (hi >= tp_px) if side == 1 else (lo <= tp_px)
            if hit_sl and hit_tp:
                exit_px = sl_px
                break
            if hit_tp:
                exit_px = tp_px
                break
            if hit_sl:
                exit_px = sl_px
                break
        if exit_px is None:
            exit_px = close[min(e + p.hold - 1, len(close) - 1)]
        roe = side * (exit_px - entry_px) / entry_px
        pnls.append(NOTIONAL * roe - fee)
        i = e + 1
        cooldown = i + 2
    return pnls


def mc_ruin(pnls: list[float], leverage: float, n_runs: int = 5000) -> dict:
    arr = np.array(pnls, dtype=np.float64) * leverage
    n = len(arr)
    if n == 0:
        return {"ruin_rate": 0, "n_trades": 0}
    rng = np.random.default_rng(42)
    final_eqs = []
    min_eqs = []
    ruin_count = 0
    for _ in range(n_runs):
        order = rng.permutation(n)
        eq = EQUITY
        min_e = eq
        for j in order:
            eq += arr[j]
            if eq < min_e:
                min_e = eq
        final_eqs.append(eq)
        min_eqs.append(min_e)
        if min_e <= EQUITY * 0.5:
            ruin_count += 1
    return {
        "leverage": leverage,
        "n_trades": n,
        "ruin_rate": ruin_count / n_runs,
        "median_final": float(np.median(final_eqs)),
        "p5_min": float(np.percentile(min_eqs, 5)),
        "median_min": float(np.median(min_eqs)),
    }


def evaluate(pnls_full: list[float], pnls_test: list[float], pnls_test_5bps: list[float], lev: float = 1.0) -> dict:
    n = len(pnls_full)
    wins = sum(1 for x in pnls_full if x > 0)
    wr = wins / n if n else 0
    total = sum(pnls_full)
    win_sum = sum(x for x in pnls_full if x > 0)
    loss_abs = sum(abs(x) for x in pnls_full if x <= 0)
    pf = win_sum / loss_abs if loss_abs > 0 else float("inf")
    test_total = sum(pnls_test)
    test_5bps_total = sum(pnls_test_5bps)
    mc = mc_ruin(pnls_full, lev)
    # Annualized at $50 equity, lev=1
    annual_50 = total * lev * (EQUITY / NOTIONAL)
    return {
        "n_trades_full_year": n,
        "wr": round(wr, 3),
        "pf": round(pf, 3) if math.isfinite(pf) else None,
        "total_pnl_100notional": round(total, 2),
        "ev_per_trade": round(total / n, 4) if n else 0,
        "test_pnl_0bps": round(test_total, 2),
        "test_pnl_5bps": round(test_5bps_total, 2),
        "slip_5bps_survives": test_5bps_total > 0,
        "annual_pnl_50equity": round(annual_50, 2),
        "annual_return_pct": round(annual_50 / EQUITY * 100, 1),
        "mc_ruin_pct": round(mc["ruin_rate"] * 100, 2),
        "mc_p5_min_eq": round(mc["p5_min"], 2),
    }


def main():
    t0 = time.time()
    universe_big = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
        "ADAUSDT", "APTUSDT", "ARBUSDT", "AVAXUSDT", "BNBUSDT",
        "DOTUSDT", "LINKUSDT", "LTCUSDT", "NEARUSDT", "OPUSDT",
        "PEPEUSDT", "SUIUSDT", "UNIUSDT", "WIFUSDT", "MATICUSDT",
    ]
    data = {}
    for s in universe_big:
        a = load_1h(s)
        ind = compute_indicators(a)
        data[s] = (a, ind)
    n_bars = len(data[universe_big[0]][0])
    split_idx = int(n_bars * 0.7)
    print(f"Loaded {len(universe_big)} symbols × 1h × {n_bars} bars in {time.time()-t0:.1f}s")
    print(f"Train [0:{split_idx}], Test [{split_idx}:{n_bars}]")
    print()

    # Best params from earlier runs:
    # X1 (rsi30/70): high-EV, broad
    # X3 (rsi25/70): more selective
    p_x1 = P(30, 70, 1.0, 0.5, 3.0, 24)
    p_x3 = P(25, 70, 1.0, 0.5, 3.0, 24)
    p_x1_us = P(30, 70, 1.0, 0.5, 3.0, 24, hour_filter=(13, 22))  # US active 13-22 UTC
    p_x1_asia = P(30, 70, 1.0, 0.5, 3.0, 24, hour_filter=(0, 8))  # Asia active 00-08 UTC

    # Strategy definitions
    strategies = [
        {
            "id": "S1_BTC_only",
            "label": "BTC 단일 (가장 안정)",
            "universe": ["BTCUSDT"],
            "params": p_x1,
            "lev": 2.0,
        },
        {
            "id": "S2_ETH_only",
            "label": "ETH 단일 (제일 신호 많음)",
            "universe": ["ETHUSDT"],
            "params": p_x1,
            "lev": 2.0,
        },
        {
            "id": "S3_top5_X1",
            "label": "Top-5 alts (OP/NEAR/SUI/ETH/UNI) + X1",
            "universe": ["OPUSDT", "NEARUSDT", "SUIUSDT", "ETHUSDT", "UNIUSDT"],
            "params": p_x1,
            "lev": 1.5,
        },
        {
            "id": "S4_majors_X1",
            "label": "Majors only (BTC/ETH/SOL) + X1",
            "universe": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "params": p_x1,
            "lev": 2.0,
        },
        {
            "id": "S5_top10_X1",
            "label": "Top-10 by edge + X1",
            "universe": ["OPUSDT", "NEARUSDT", "SUIUSDT", "ETHUSDT", "UNIUSDT",
                         "AVAXUSDT", "LINKUSDT", "SOLUSDT", "ADAUSDT", "LTCUSDT"],
            "params": p_x1,
            "lev": 1.5,
        },
        {
            "id": "S6_X1_US_session",
            "label": "X1 + US session 만 (13-22 UTC)",
            "universe": universe_big,
            "params": p_x1_us,
            "lev": 1.5,
        },
        {
            "id": "S7_X1_Asia_session",
            "label": "X1 + Asia session 만 (00-08 UTC)",
            "universe": universe_big,
            "params": p_x1_asia,
            "lev": 1.5,
        },
        {
            "id": "S8_top5_X3_selective",
            "label": "Top-5 + X3 (rsi25 더 selective)",
            "universe": ["OPUSDT", "NEARUSDT", "SUIUSDT", "ETHUSDT", "UNIUSDT"],
            "params": p_x3,
            "lev": 2.0,
        },
        {
            "id": "S9_BTC_ETH_only_X1",
            "label": "BTC+ETH only + X1 (가장 보수적 multi)",
            "universe": ["BTCUSDT", "ETHUSDT"],
            "params": p_x1,
            "lev": 2.0,
        },
    ]

    results = []
    for cfg in strategies:
        pnls_full: list[float] = []
        pnls_test_0: list[float] = []
        pnls_test_5: list[float] = []
        for s in cfg["universe"]:
            a, ind = data[s]
            pnls_full.extend(collect_pnls(a, ind, cfg["params"], 0, n_bars))
            pnls_test_0.extend(collect_pnls(a, ind, cfg["params"], split_idx, n_bars, extra_bps=0))
            pnls_test_5.extend(collect_pnls(a, ind, cfg["params"], split_idx, n_bars, extra_bps=5))
        ev = evaluate(pnls_full, pnls_test_0, pnls_test_5, lev=cfg["lev"])
        ev["id"] = cfg["id"]
        ev["label"] = cfg["label"]
        ev["universe"] = cfg["universe"]
        ev["lev"] = cfg["lev"]
        ev["params"] = cfg["params"].__dict__
        results.append(ev)
        print(f"\n=== {cfg['id']}  ({cfg['label']}) ===")
        print(f"  universe={cfg['universe']}  lev={cfg['lev']}x")
        print(f"  N={ev['n_trades_full_year']}  WR={ev['wr']}  PF={ev['pf']}  total=${ev['total_pnl_100notional']}")
        print(f"  EV/trade=${ev['ev_per_trade']}  test 0bps=${ev['test_pnl_0bps']}  test 5bps=${ev['test_pnl_5bps']} ({'✓' if ev['slip_5bps_survives'] else '✗'})")
        print(f"  $50 lev{cfg['lev']}x: 연 PnL ${ev['annual_pnl_50equity']:+.1f} = {ev['annual_return_pct']}%/yr")
        print(f"  MC ruin = {ev['mc_ruin_pct']}%  p5_min=${ev['mc_p5_min_eq']}")

    # Rank: 5bps survival × MC ruin <= 10% × annual_return
    def gate_score(r):
        slip_ok = r["slip_5bps_survives"]
        mc_ok = r["mc_ruin_pct"] <= 10
        n_ok = r["n_trades_full_year"] >= 30
        return (int(slip_ok and mc_ok and n_ok), r["annual_return_pct"])

    results.sort(key=gate_score, reverse=True)

    print()
    print("=" * 80)
    print("RANKED — gate: 5bps survive ✓ AND MC ruin ≤ 10% AND N ≥ 30")
    print("=" * 80)
    for r in results:
        gate_pass = r["slip_5bps_survives"] and r["mc_ruin_pct"] <= 10 and r["n_trades_full_year"] >= 30
        mark = "✓" if gate_pass else "✗"
        print(f"  {mark} [{r['id']:30s}] N={r['n_trades_full_year']:>3d} WR={r['wr']:.3f} 5bps=${r['test_pnl_5bps']:+.2f} ruin={r['mc_ruin_pct']:>4.1f}% → {r['annual_return_pct']}%/yr ({r['label']})")

    OUT.write_text(json.dumps({"strategies": results}, indent=2, default=str))
    print(f"\nElapsed: {time.time() - t0:.1f}s, saved: {OUT}")


if __name__ == "__main__":
    main()
