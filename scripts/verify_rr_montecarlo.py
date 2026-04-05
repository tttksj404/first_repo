#!/usr/bin/env python3
"""
R:R & Monte Carlo Ruin Verification
=====================================
1h 타임프레임 통일 후 검증:
- ATR-14 (1h) 기반 실제 SL 거리 계산
- Swing TP와 SL의 R:R 비율
- 몬테카를로 파산확률 시뮬레이션
- 최적 전략 (EMA 9/21 + ADX≥28) 기준

검증 기준:
- R:R >= 1.5 (TP/SL)
- 몬테카를로 파산확률 < 5%
- Profit Factor > 1.3
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

HIST_DIR = Path(__file__).resolve().parent.parent / "quant_runtime" / "historical"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
FUTURES_FEE_BPS = 4.0
SLIPPAGE_BPS = 3.0
ATR_STOP_MULTIPLE = 1.5  # config.example.json default
STOP_FLOOR_BPS = 45.0


def load_candles(symbol: str, tf: str) -> list[dict]:
    path = HIST_DIR / symbol / f"{tf}.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def candles_to_arrays(candles: list[dict]) -> dict[str, np.ndarray]:
    if not candles:
        return {}
    return {
        "time": np.array([c["open_time"] for c in candles], dtype=np.int64),
        "open": np.array([c["open_price"] for c in candles], dtype=np.float64),
        "high": np.array([c["high_price"] for c in candles], dtype=np.float64),
        "low": np.array([c["low_price"] for c in candles], dtype=np.float64),
        "close": np.array([c["close_price"] for c in candles], dtype=np.float64),
        "volume": np.array([c["quote_volume"] for c in candles], dtype=np.float64),
    }


# ── 지표 ──────────────────────────────────────────────
def ema(arr, period):
    result = np.full_like(arr, np.nan, dtype=np.float64)
    if len(arr) < period:
        return result
    alpha = 2.0 / (period + 1)
    result[period - 1] = np.mean(arr[:period])
    for i in range(period, len(arr)):
        result[i] = alpha * arr[i] + (1 - alpha) * result[i - 1]
    return result


def atr_array(high, low, close, period=14):
    result = np.full_like(close, np.nan)
    if len(close) < period + 1:
        return result
    tr = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])))
    av = np.full(len(tr), np.nan)
    av[period - 1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        av[i] = (av[i - 1] * (period - 1) + tr[i]) / period
    result[1:] = av
    return result


def adx_array(high, low, close, period=14):
    result = np.full_like(close, np.nan)
    n = len(close)
    if n < 2 * period + 1:
        return result
    up = high[1:] - high[:-1]
    down = low[:-1] - low[1:]
    pdm = np.where((up > down) & (up > 0), up, 0.0)
    mdm = np.where((down > up) & (down > 0), down, 0.0)
    tr = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])))
    st = np.full(len(tr), np.nan)
    sp = np.full(len(tr), np.nan)
    sm = np.full(len(tr), np.nan)
    st[period - 1] = np.sum(tr[:period])
    sp[period - 1] = np.sum(pdm[:period])
    sm[period - 1] = np.sum(mdm[:period])
    for i in range(period, len(tr)):
        st[i] = st[i - 1] - st[i - 1] / period + tr[i]
        sp[i] = sp[i - 1] - sp[i - 1] / period + pdm[i]
        sm[i] = sm[i - 1] - sm[i - 1] / period + mdm[i]
    pdi = 100.0 * sp / np.where(st == 0, 1e-10, st)
    mdi = 100.0 * sm / np.where(st == 0, 1e-10, st)
    dx = 100.0 * np.abs(pdi - mdi) / np.where((pdi + mdi) == 0, 1e-10, pdi + mdi)
    av = np.full(len(dx), np.nan)
    start = 2 * period - 1
    if start < len(dx):
        av[start] = np.mean(dx[period - 1:start + 1])
        for i in range(start + 1, len(dx)):
            av[i] = (av[i - 1] * (period - 1) + dx[i]) / period
    result[1:] = av
    return result


def volume_sma(vol, period=20):
    result = np.full_like(vol, np.nan, dtype=np.float64)
    if len(vol) < period:
        return result
    cs = np.cumsum(vol)
    result[period - 1:] = (cs[period - 1:] - np.concatenate([[0], cs[:-period]])) / period
    return result


# ── R:R 분석 포함 백테스트 ────────────────────────────
def backtest_with_rr(data_1h, *, fast=9, slow=21, adx_min=28.0,
                     atr_stop_mult=ATR_STOP_MULTIPLE, hold_bars=12):
    """
    Backtest on 1h with explicit SL (ATR-based) and TP (ATR-based R:R target).
    Returns trade-level details including R:R ratios.
    """
    close = data_1h["close"]
    high = data_1h["high"]
    low = data_1h["low"]
    ef = ema(close, fast)
    es = ema(close, slow)
    adx_v = adx_array(high, low, close)
    atr_v = atr_array(high, low, close)
    cost_bps = 2 * FUTURES_FEE_BPS + 2 * SLIPPAGE_BPS  # 14 bps round trip

    trades = []
    i = max(slow + 1, 30)
    while i < len(close) - hold_bars:
        if np.isnan(ef[i]) or np.isnan(es[i]) or np.isnan(ef[i-1]) or np.isnan(es[i-1]):
            i += 1; continue
        if np.isnan(adx_v[i]) or adx_v[i] < adx_min:
            i += 1; continue
        if np.isnan(atr_v[i]) or atr_v[i] <= 0:
            i += 1; continue

        cross_up = ef[i-1] <= es[i-1] and ef[i] > es[i]
        cross_down = ef[i-1] >= es[i-1] and ef[i] < es[i]
        if not (cross_up or cross_down):
            i += 1; continue

        side = "long" if cross_up else "short"
        entry = close[i]
        atr_price = atr_v[i]

        # ── SL & TP levels (1h ATR based) ──
        sl_distance_price = atr_stop_mult * atr_price
        sl_distance_bps = max(sl_distance_price / entry * 10000, STOP_FLOOR_BPS)
        # TP target: 2.0x R:R (swing target = 2x ATR stop)
        tp_distance_price = 2.0 * sl_distance_price
        tp_distance_bps = tp_distance_price / entry * 10000

        if side == "long":
            sl_price = entry - sl_distance_price
            tp_price = entry + tp_distance_price
        else:
            sl_price = entry + sl_distance_price
            tp_price = entry - tp_distance_price

        # ── Simulate exit ──
        exit_idx = min(i + hold_bars, len(close) - 1)
        exit_reason = "TIME"
        for j in range(i + 1, exit_idx + 1):
            if side == "long":
                if low[j] <= sl_price:
                    exit_idx = j
                    exit_reason = "SL"
                    break
                if high[j] >= tp_price:
                    exit_idx = j
                    exit_reason = "TP"
                    break
            else:
                if high[j] >= sl_price:
                    exit_idx = j
                    exit_reason = "SL"
                    break
                if low[j] <= tp_price:
                    exit_idx = j
                    exit_reason = "TP"
                    break

        exit_price = close[exit_idx]
        # For SL/TP exits, use the level price
        if exit_reason == "SL":
            exit_price = sl_price
        elif exit_reason == "TP":
            exit_price = tp_price

        if side == "long":
            raw_bps = (exit_price - entry) / entry * 10000
        else:
            raw_bps = (entry - exit_price) / entry * 10000
        net_bps = raw_bps - cost_bps

        trades.append({
            "entry_idx": i,
            "side": side,
            "entry": entry,
            "exit": exit_price,
            "atr_1h_price": atr_price,
            "atr_1h_bps": atr_price / entry * 10000,
            "sl_bps": sl_distance_bps,
            "tp_bps": tp_distance_bps,
            "rr_ratio": tp_distance_bps / sl_distance_bps if sl_distance_bps > 0 else 0,
            "raw_bps": raw_bps,
            "net_bps": net_bps,
            "exit_reason": exit_reason,
            "holding_bars": exit_idx - i,
            "adx": adx_v[i],
        })
        i = exit_idx + 1

    return trades


def monte_carlo_ruin(trade_returns_bps: list[float], n_sims: int = 10000,
                     n_trades_per_sim: int = 200, ruin_pct: float = -30.0) -> dict:
    """
    Monte Carlo ruin probability simulation.
    Resamples from observed trade returns, tracks equity curve.
    Ruin = drawdown exceeds ruin_pct of starting equity.
    """
    if not trade_returns_bps or len(trade_returns_bps) < 3:
        return {"ruin_prob": 1.0, "msg": "insufficient trades"}

    returns = np.array(trade_returns_bps)
    ruin_count = 0
    max_dds = []
    final_equities = []

    rng = np.random.default_rng(42)
    for _ in range(n_sims):
        sampled = rng.choice(returns, size=n_trades_per_sim, replace=True)
        equity = np.cumsum(sampled)
        peak = np.maximum.accumulate(equity)
        dd = equity - peak
        max_dd = np.min(dd)
        max_dds.append(max_dd)
        final_equities.append(equity[-1])

        # Ruin threshold: cumulative drawdown in bps
        # -30% equity with 1% risk/trade ≈ -3000 bps cumulative
        ruin_threshold_bps = ruin_pct / 100.0 * 10000  # -3000 bps
        if max_dd < ruin_threshold_bps:
            ruin_count += 1

    return {
        "ruin_prob": ruin_count / n_sims,
        "median_max_dd_bps": float(np.median(max_dds)),
        "p95_max_dd_bps": float(np.percentile(max_dds, 5)),  # worst 5%
        "median_final_equity_bps": float(np.median(final_equities)),
        "p5_final_equity_bps": float(np.percentile(final_equities, 5)),
    }


def main():
    print("=" * 90)
    print("R:R & MONTE CARLO RUIN VERIFICATION")
    print("1h Timeframe Unified — EMA 9/21 + ADX >= 28")
    print("=" * 90)

    all_trades = []
    results_by_symbol = {}

    for symbol in SYMBOLS:
        d1h = candles_to_arrays(load_candles(symbol, "1h"))
        if not d1h:
            print(f"\n  {symbol}: [SKIP] no data")
            continue

        print(f"\n{'─' * 70}")
        print(f"  {symbol}")
        print(f"{'─' * 70}")

        trades = backtest_with_rr(d1h)
        results_by_symbol[symbol] = trades
        all_trades.extend(trades)

        if not trades:
            print("  No trades generated")
            continue

        # ── R:R Analysis ──
        rr_ratios = [t["rr_ratio"] for t in trades]
        sl_bps_vals = [t["sl_bps"] for t in trades]
        tp_bps_vals = [t["tp_bps"] for t in trades]
        atr_bps_vals = [t["atr_1h_bps"] for t in trades]
        net_returns = [t["net_bps"] for t in trades]
        exit_reasons = [t["exit_reason"] for t in trades]

        wins = sum(1 for r in net_returns if r > 0)
        n = len(trades)
        win_rate = wins / n if n > 0 else 0
        gross_profit = sum(r for r in net_returns if r > 0)
        gross_loss = abs(sum(r for r in net_returns if r < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        tp_count = exit_reasons.count("TP")
        sl_count = exit_reasons.count("SL")
        time_count = exit_reasons.count("TIME")

        print(f"\n  Trades: {n}")
        print(f"  Win Rate: {win_rate:.1%}")
        print(f"  Profit Factor: {pf:.2f}" if pf < 100 else f"  Profit Factor: inf")
        print(f"  Total Return: {sum(net_returns):.0f} bps")
        print(f"  Avg Return: {np.mean(net_returns):.1f} bps")
        print(f"\n  Exit Reasons: TP={tp_count} SL={sl_count} TIME={time_count}")
        print(f"\n  ATR(1h) mean: {np.mean(atr_bps_vals):.0f} bps")
        print(f"  SL distance mean: {np.mean(sl_bps_vals):.0f} bps (ATR×{ATR_STOP_MULTIPLE})")
        print(f"  TP distance mean: {np.mean(tp_bps_vals):.0f} bps (2× SL)")
        print(f"  R:R ratio mean: {np.mean(rr_ratios):.2f}")
        print(f"  R:R ratio min: {min(rr_ratios):.2f}")

        # Check R:R >= 1.5
        rr_pass = np.mean(rr_ratios) >= 1.5
        print(f"\n  R:R >= 1.5: {'PASS' if rr_pass else 'FAIL'} (avg={np.mean(rr_ratios):.2f})")

        # ── Monte Carlo ──
        mc = monte_carlo_ruin(net_returns)
        ruin_pass = mc["ruin_prob"] < 0.05
        print(f"\n  Monte Carlo ({len(net_returns)} trades, 10k sims, 200 trades/sim):")
        print(f"    Ruin Probability (<5%): {mc['ruin_prob']:.1%} {'PASS' if ruin_pass else 'FAIL'}")
        print(f"    Median Max DD: {mc['median_max_dd_bps']:.0f} bps")
        print(f"    P95 Max DD: {mc['p95_max_dd_bps']:.0f} bps")
        print(f"    Median Final Equity: {mc['median_final_equity_bps']:.0f} bps")
        print(f"    P5 Final Equity: {mc['p5_final_equity_bps']:.0f} bps")

    # ── Aggregate Results ──
    print(f"\n\n{'=' * 90}")
    print("  AGGREGATE RESULTS (ALL SYMBOLS)")
    print(f"{'=' * 90}")

    if not all_trades:
        print("  No trades across all symbols!")
        return

    all_net = [t["net_bps"] for t in all_trades]
    all_rr = [t["rr_ratio"] for t in all_trades]
    all_sl = [t["sl_bps"] for t in all_trades]
    all_atr = [t["atr_1h_bps"] for t in all_trades]
    all_exit = [t["exit_reason"] for t in all_trades]

    n = len(all_trades)
    wins = sum(1 for r in all_net if r > 0)
    gp = sum(r for r in all_net if r > 0)
    gl = abs(sum(r for r in all_net if r < 0))
    pf = gp / gl if gl > 0 else float("inf")

    print(f"\n  Total Trades: {n}")
    print(f"  Win Rate: {wins/n:.1%}")
    pf_str = f"{pf:.2f}" if pf < 100 else "inf"
    print(f"  Profit Factor: {pf_str}")
    print(f"  Total Return: {sum(all_net):.0f} bps")
    print(f"  Avg Return: {np.mean(all_net):.1f} bps")
    print(f"\n  Exit Distribution: TP={all_exit.count('TP')} SL={all_exit.count('SL')} TIME={all_exit.count('TIME')}")
    print(f"\n  ATR(1h) mean: {np.mean(all_atr):.0f} bps")
    print(f"  SL mean: {np.mean(all_sl):.0f} bps")
    print(f"  R:R mean: {np.mean(all_rr):.2f}")

    # ── Aggregate Monte Carlo ──
    mc_all = monte_carlo_ruin(all_net)
    print(f"\n  Monte Carlo (aggregated {n} trades):")
    print(f"    Ruin Probability: {mc_all['ruin_prob']:.1%}")
    print(f"    Median Max DD: {mc_all['median_max_dd_bps']:.0f} bps")
    print(f"    P95 Max DD: {mc_all['p95_max_dd_bps']:.0f} bps")
    print(f"    Median Final Equity: {mc_all['median_final_equity_bps']:.0f} bps")

    # ── Final Verdict ──
    print(f"\n{'=' * 90}")
    print("  VERIFICATION VERDICT")
    print(f"{'=' * 90}")

    checks = {
        "R:R >= 1.5": np.mean(all_rr) >= 1.5,
        "Profit Factor > 1.3": pf > 1.3,
        "Win Rate > 40%": wins / n > 0.4,
        "MC Ruin < 5%": mc_all["ruin_prob"] < 0.05,
        "MC Ruin < 10%": mc_all["ruin_prob"] < 0.10,
        "Avg Return > 0": np.mean(all_net) > 0,
        "Total Trades >= 15": n >= 15,
    }

    for check, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {check}")

    all_pass = all(checks.values())
    print(f"\n  {'ALL CHECKS PASSED — LIVE ELIGIBLE' if all_pass else 'CHECKS FAILED — NOT LIVE ELIGIBLE'}")

    # Save detailed results
    output_dir = Path(__file__).resolve().parent.parent / "quant_runtime" / "output" / "signal_research"
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "v3_rr_montecarlo.json", "w") as f:
        json.dump({
            "verification": {k: bool(v) for k, v in checks.items()},
            "aggregate": {
                "total_trades": n, "win_rate": round(wins/n, 4),
                "profit_factor": round(pf, 4) if pf < 1000 else None,
                "total_return_bps": round(sum(all_net), 2),
                "avg_return_bps": round(float(np.mean(all_net)), 2),
                "avg_rr": round(float(np.mean(all_rr)), 4),
                "mc_ruin_prob": round(mc_all["ruin_prob"], 4),
                "mc_median_max_dd_bps": round(mc_all["median_max_dd_bps"], 2),
            },
            "by_symbol": {
                sym: {
                    "trades": len(ts),
                    "win_rate": round(sum(1 for t in ts if t["net_bps"] > 0) / len(ts), 4) if ts else 0,
                    "avg_rr": round(float(np.mean([t["rr_ratio"] for t in ts])), 4) if ts else 0,
                    "avg_atr_bps": round(float(np.mean([t["atr_1h_bps"] for t in ts])), 2) if ts else 0,
                    "avg_sl_bps": round(float(np.mean([t["sl_bps"] for t in ts])), 2) if ts else 0,
                    "total_return_bps": round(sum(t["net_bps"] for t in ts), 2) if ts else 0,
                }
                for sym, ts in results_by_symbol.items()
            },
        }, f, indent=2)
    print(f"\n결과 저장: {output_dir / 'v3_rr_montecarlo.json'}")


if __name__ == "__main__":
    main()
