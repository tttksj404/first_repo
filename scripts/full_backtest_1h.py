#!/usr/bin/env python3
"""1h 봉 375일 × 20코인 전면 백테스트.

- ccxt로 Bitget 1h kline 다운로드 (375일)
- coin_profiles.py 파라미터 기반 EMA cross + ADX 전략
- 1h 단위 TP/SL 체크
- In-sample(75%) / Out-of-sample(25%) 분리
- 코인별 PF / 승률 / MDD 리포트

Usage:
    python3 scripts/full_backtest_1h.py [--skip-download] [--data-dir PATH]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# ── 프로젝트 루트를 sys.path에 추가 ──────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from quant_binance.strategy.coin_profiles import (
    COIN_PROFILES,
    DEFAULT_PROFILE,
    CoinProfile,
    get_profile,
)

# ── 20개 코인 유니버스 ──────────────────────────────────────
UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
    "ADAUSDT", "DOGEUSDT", "MATICUSDT", "LTCUSDT", "LINKUSDT",
    "PEPEUSDT", "AVAXUSDT", "DOTUSDT", "TRXUSDT", "SHIBUSDT",
    "SUIUSDT", "AAVEUSDT", "APTUSDT", "NEARUSDT", "ARBUSDT",
]

DAYS = 375
WARMUP_BARS = 60  # EMA slow=50 + ADX=14 warmup
COST_BPS = 16.0   # 편도 8bps × 2 (수수료+슬리피지)
EQUITY_USD = 10_000.0


# ═══════════════════════════════════════════════════════════════
#  1. DATA DOWNLOAD (ccxt → Bitget 1h klines)
# ═══════════════════════════════════════════════════════════════

def download_1h_klines(symbols: list[str], days: int, data_dir: Path) -> dict[str, pd.DataFrame]:
    """ccxt Bitget에서 1h klines 다운로드. 캐시 있으면 스킵."""
    import ccxt

    exchange = ccxt.bitget({
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })
    exchange.load_markets()

    dfs: dict[str, pd.DataFrame] = {}
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - days * 86_400_000

    for sym in symbols:
        cache_path = data_dir / f"{sym}_1h.csv"
        if cache_path.exists():
            df = pd.read_csv(cache_path)
            cached_days = (df["timestamp"].max() - df["timestamp"].min()) / 86_400_000
            if cached_days >= days * 0.85:
                print(f"  [{sym}] cached ({len(df)} bars, {cached_days:.0f}d)")
                dfs[sym] = df
                continue

        # Bitget swap symbol mapping
        ccxt_sym = sym.replace("USDT", "/USDT:USDT")
        if ccxt_sym not in exchange.markets:
            # 일부 코인은 심볼 형식이 다를 수 있음
            alt = sym.replace("USDT", "/USDT")
            if alt in exchange.markets:
                ccxt_sym = alt
            else:
                print(f"  [{sym}] NOT FOUND in Bitget markets, skipping")
                continue

        print(f"  [{sym}] downloading 1h klines ({days}d)...", end="", flush=True)
        all_ohlcv = []
        cursor = start_ms

        while cursor < now_ms:
            try:
                batch = exchange.fetch_ohlcv(ccxt_sym, "1h", since=cursor, limit=200)
            except Exception as e:
                print(f"\n    Error fetching {sym}: {e}")
                time.sleep(3)
                try:
                    batch = exchange.fetch_ohlcv(ccxt_sym, "1h", since=cursor, limit=200)
                except Exception:
                    break
            if not batch:
                break
            all_ohlcv.extend(batch)
            cursor = batch[-1][0] + 1
            time.sleep(0.3)

        if not all_ohlcv:
            print(f" EMPTY")
            continue

        df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        data_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache_path, index=False)
        print(f" {len(df)} bars")
        dfs[sym] = df

    return dfs


def load_cached_data(symbols: list[str], data_dir: Path) -> dict[str, pd.DataFrame]:
    """캐시된 parquet만 로드."""
    dfs = {}
    for sym in symbols:
        path = data_dir / f"{sym}_1h.csv"
        if path.exists():
            dfs[sym] = pd.read_csv(path)
    return dfs


# ═══════════════════════════════════════════════════════════════
#  2. INDICATORS
# ═══════════════════════════════════════════════════════════════

def compute_ema(series: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average."""
    alpha = 2.0 / (period + 1)
    ema = np.empty_like(series, dtype=np.float64)
    ema[0] = series[0]
    for i in range(1, len(series)):
        ema[i] = alpha * series[i] + (1 - alpha) * ema[i - 1]
    return ema


def compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Average True Range."""
    n = len(high)
    tr = np.empty(n, dtype=np.float64)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    atr = np.empty(n, dtype=np.float64)
    atr[:period] = np.nan
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def compute_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Average Directional Index."""
    n = len(high)
    adx = np.full(n, np.nan, dtype=np.float64)
    if n < period * 2 + 1:
        return adx

    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr = np.zeros(n)

    for i in range(1, n):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    # Smoothed
    smooth_tr = np.zeros(n)
    smooth_plus = np.zeros(n)
    smooth_minus = np.zeros(n)

    smooth_tr[period] = np.sum(tr[1:period + 1])
    smooth_plus[period] = np.sum(plus_dm[1:period + 1])
    smooth_minus[period] = np.sum(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        smooth_tr[i] = smooth_tr[i - 1] - smooth_tr[i - 1] / period + tr[i]
        smooth_plus[i] = smooth_plus[i - 1] - smooth_plus[i - 1] / period + plus_dm[i]
        smooth_minus[i] = smooth_minus[i - 1] - smooth_minus[i - 1] / period + minus_dm[i]

    dx = np.zeros(n)
    for i in range(period, n):
        if smooth_tr[i] == 0:
            continue
        plus_di = 100.0 * smooth_plus[i] / smooth_tr[i]
        minus_di = 100.0 * smooth_minus[i] / smooth_tr[i]
        denom = plus_di + minus_di
        if denom > 0:
            dx[i] = 100.0 * abs(plus_di - minus_di) / denom

    # ADX = smoothed DX
    start = period * 2
    if start < n:
        adx[start] = np.mean(dx[period:start + 1])
        for i in range(start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return adx


# ═══════════════════════════════════════════════════════════════
#  3. SIGNAL GENERATION (coin_profiles 기반)
# ═══════════════════════════════════════════════════════════════

@dataclass
class Signal:
    bar_idx: int
    side: int          # +1 long, -1 short
    entry_price: float
    sl_bps: float      # stop distance in bps
    tp_bps: float      # take-profit distance in bps
    hold_bars: int     # max holding period
    signal_type: str   # "ema_cross" | "pullback"


def generate_signals(df: pd.DataFrame, profile: CoinProfile) -> list[Signal]:
    """EMA cross + ADX 전략 시그널 생성."""
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    n = len(close)

    ema_fast = compute_ema(close, profile.ema_fast)
    ema_slow = compute_ema(close, profile.ema_slow)
    adx = compute_adx(high, low, close, 14)
    atr = compute_atr(high, low, close, 14)

    # Pullback용 EMA (활성화된 경우)
    pullback_ema_arr = None
    if profile.pullback_ema > 0:
        pullback_ema_arr = compute_ema(close, profile.pullback_ema)
        # RSI 14
        rsi = _compute_rsi(close, 14)

    signals: list[Signal] = []
    in_trade_until = 0  # 중복 진입 방지

    for i in range(max(WARMUP_BARS, profile.ema_slow + 14), n):
        if i < in_trade_until:
            continue
        if np.isnan(adx[i]) or np.isnan(atr[i]) or atr[i] <= 0:
            continue

        # ── EMA Cross Signal ──
        cross_long = ema_fast[i] > ema_slow[i] and ema_fast[i - 1] <= ema_slow[i - 1]
        cross_short = ema_fast[i] < ema_slow[i] and ema_fast[i - 1] >= ema_slow[i - 1]

        if adx[i] >= profile.adx_floor:
            side = 0
            if cross_long and profile.side_filter in ("both", "long"):
                side = +1
            elif cross_short and profile.side_filter == "both":
                side = -1

            if side != 0:
                sl_bps = profile.sl_atr_mult * (atr[i] / close[i]) * 10000
                sl_bps = max(sl_bps, 10.0)  # floor 10bps
                tp_bps = sl_bps * profile.rr
                signals.append(Signal(
                    bar_idx=i, side=side, entry_price=close[i],
                    sl_bps=sl_bps, tp_bps=tp_bps,
                    hold_bars=profile.hold_bars, signal_type="ema_cross",
                ))
                in_trade_until = i + max(3, profile.hold_bars // 4)  # 쿨다운
                continue

        # ── Pullback Signal ──
        if pullback_ema_arr is not None and profile.pullback_adx_floor > 0:
            if adx[i] >= profile.pullback_adx_floor:
                # Long pullback: price > EMA, RSI recovers from < 40
                if (close[i] > pullback_ema_arr[i]
                        and rsi[i] >= 40 and rsi[i - 1] < 40
                        and profile.side_filter in ("both", "long")):
                    sl_bps = profile.pullback_sl_mult * (atr[i] / close[i]) * 10000
                    sl_bps = max(sl_bps, 10.0)
                    tp_bps = sl_bps * profile.pullback_rr
                    signals.append(Signal(
                        bar_idx=i, side=+1, entry_price=close[i],
                        sl_bps=sl_bps, tp_bps=tp_bps,
                        hold_bars=profile.hold_bars, signal_type="pullback",
                    ))
                    in_trade_until = i + max(3, profile.hold_bars // 4)

    return signals


def _compute_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI(14) 계산."""
    n = len(close)
    rsi = np.full(n, 50.0, dtype=np.float64)
    if n < period + 1:
        return rsi

    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - 100.0 / (1.0 + rs)

    return rsi


# ═══════════════════════════════════════════════════════════════
#  4. TRADE SIMULATION (1h 단위 TP/SL 체크)
# ═══════════════════════════════════════════════════════════════

@dataclass
class Trade:
    symbol: str
    signal_type: str
    side: int
    entry_bar: int
    entry_price: float
    exit_bar: int
    exit_price: float
    pnl_bps: float
    exit_reason: str   # "TP" | "SL" | "MAX_HOLD"


def simulate_trades(
    df: pd.DataFrame,
    signals: list[Signal],
    symbol: str,
    cost_bps: float = COST_BPS,
) -> list[Trade]:
    """시그널 리스트 → Trade 리스트. 1h bar마다 TP/SL 체크."""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(close)
    trades: list[Trade] = []

    for sig in signals:
        entry_bar = sig.bar_idx
        entry_price = sig.entry_price
        if entry_bar + 1 >= n:
            continue

        sl_price = entry_price * (1 - sig.side * sig.sl_bps / 10000)
        tp_price = entry_price * (1 + sig.side * sig.tp_bps / 10000)

        exit_bar = None
        exit_price = None
        exit_reason = None

        for j in range(entry_bar + 1, min(entry_bar + sig.hold_bars + 1, n)):
            bar_high = high[j]
            bar_low = low[j]

            # SL 체크 (불리한 방향)
            if sig.side == 1:
                if bar_low <= sl_price:
                    exit_bar, exit_price, exit_reason = j, sl_price, "SL"
                    break
                if bar_high >= tp_price:
                    exit_bar, exit_price, exit_reason = j, tp_price, "TP"
                    break
            else:
                if bar_high >= sl_price:
                    exit_bar, exit_price, exit_reason = j, sl_price, "SL"
                    break
                if bar_low <= tp_price:
                    exit_bar, exit_price, exit_reason = j, tp_price, "TP"
                    break

        # Max hold: close로 청산
        if exit_bar is None:
            exit_idx = min(entry_bar + sig.hold_bars, n - 1)
            exit_bar = exit_idx
            exit_price = close[exit_idx]
            exit_reason = "MAX_HOLD"

        gross_bps = sig.side * (exit_price / entry_price - 1) * 10000
        net_bps = gross_bps - cost_bps
        trades.append(Trade(
            symbol=symbol, signal_type=sig.signal_type, side=sig.side,
            entry_bar=entry_bar, entry_price=entry_price,
            exit_bar=exit_bar, exit_price=exit_price,
            pnl_bps=net_bps, exit_reason=exit_reason,
        ))

    return trades


# ═══════════════════════════════════════════════════════════════
#  5. METRICS
# ═══════════════════════════════════════════════════════════════

@dataclass
class CoinResult:
    symbol: str
    n_trades: int
    win_rate: float
    profit_factor: float
    total_pnl_bps: float
    avg_pnl_bps: float
    max_drawdown_bps: float
    n_tp: int
    n_sl: int
    n_hold: int
    sample_label: str  # "IS" | "OOS" | "FULL"


def compute_metrics(trades: list[Trade], symbol: str, label: str) -> CoinResult:
    """트레이드 리스트 → PF/승률/MDD."""
    if not trades:
        return CoinResult(symbol, 0, 0, 0, 0, 0, 0, 0, 0, 0, label)

    wins = [t for t in trades if t.pnl_bps > 0]
    losses = [t for t in trades if t.pnl_bps <= 0]

    total_wins_bps = sum(t.pnl_bps for t in wins) if wins else 0.0
    total_losses_bps = abs(sum(t.pnl_bps for t in losses)) if losses else 0.0

    pf = total_wins_bps / total_losses_bps if total_losses_bps > 0 else float("inf")
    wr = len(wins) / len(trades) if trades else 0.0

    # MDD (equity curve from cumulative bps)
    cum_pnl = np.cumsum([t.pnl_bps for t in trades])
    peak = np.maximum.accumulate(cum_pnl)
    drawdown = cum_pnl - peak
    mdd = float(np.min(drawdown)) if len(drawdown) > 0 else 0.0

    n_tp = sum(1 for t in trades if t.exit_reason == "TP")
    n_sl = sum(1 for t in trades if t.exit_reason == "SL")
    n_hold = sum(1 for t in trades if t.exit_reason == "MAX_HOLD")

    return CoinResult(
        symbol=symbol,
        n_trades=len(trades),
        win_rate=wr,
        profit_factor=pf,
        total_pnl_bps=float(cum_pnl[-1]) if len(cum_pnl) > 0 else 0.0,
        avg_pnl_bps=float(np.mean([t.pnl_bps for t in trades])),
        max_drawdown_bps=mdd,
        n_tp=n_tp, n_sl=n_sl, n_hold=n_hold,
        sample_label=label,
    )


# ═══════════════════════════════════════════════════════════════
#  6. MAIN
# ═══════════════════════════════════════════════════════════════

def print_results_table(results: list[CoinResult], title: str):
    """결과 테이블 출력."""
    print(f"\n{'='*100}")
    print(f"  {title}")
    print(f"{'='*100}")
    header = f"{'Symbol':<12} {'Trades':>6} {'WR%':>7} {'PF':>7} {'TotalBps':>10} {'AvgBps':>8} {'MDD_Bps':>9} {'TP':>4} {'SL':>4} {'HOLD':>5}"
    print(header)
    print("-" * 100)

    total_trades = 0
    total_pnl = 0.0
    total_wins = 0

    for r in sorted(results, key=lambda x: x.total_pnl_bps, reverse=True):
        pf_str = f"{r.profit_factor:.2f}" if r.profit_factor < 100 else "INF"
        print(
            f"{r.symbol:<12} {r.n_trades:>6} {r.win_rate*100:>6.1f}% {pf_str:>7} "
            f"{r.total_pnl_bps:>+10.1f} {r.avg_pnl_bps:>+8.1f} {r.max_drawdown_bps:>9.1f} "
            f"{r.n_tp:>4} {r.n_sl:>4} {r.n_hold:>5}"
        )
        total_trades += r.n_trades
        total_pnl += r.total_pnl_bps
        total_wins += int(r.n_trades * r.win_rate)

    print("-" * 100)
    agg_wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    print(f"{'TOTAL':<12} {total_trades:>6} {agg_wr:>6.1f}%         {total_pnl:>+10.1f}")
    print()


def print_overfit_comparison(is_results: list[CoinResult], oos_results: list[CoinResult]):
    """IS vs OOS 과적합 검증 테이블."""
    print(f"\n{'='*110}")
    print("  OVERFITTING CHECK: In-Sample(75%) vs Out-of-Sample(25%)")
    print(f"{'='*110}")
    header = (
        f"{'Symbol':<12} │ {'IS_WR%':>7} {'IS_PF':>7} {'IS_Avg':>8} │ "
        f"{'OOS_WR%':>7} {'OOS_PF':>7} {'OOS_Avg':>8} │ {'WR_Diff':>8} {'PF_Ratio':>8} {'Verdict':>10}"
    )
    print(header)
    print("-" * 110)

    is_map = {r.symbol: r for r in is_results}
    oos_map = {r.symbol: r for r in oos_results}

    overfit_count = 0
    total = 0

    for sym in sorted(set(is_map.keys()) | set(oos_map.keys())):
        is_r = is_map.get(sym)
        oos_r = oos_map.get(sym)
        if not is_r or not oos_r or is_r.n_trades == 0:
            continue

        total += 1
        wr_diff = (oos_r.win_rate - is_r.win_rate) * 100
        pf_ratio = oos_r.profit_factor / is_r.profit_factor if is_r.profit_factor > 0 else 0

        # 과적합 판정: OOS PF < IS PF의 50% 이거나 OOS WR < IS WR - 15%p
        is_overfit = pf_ratio < 0.5 or wr_diff < -15
        verdict = "OVERFIT" if is_overfit else "OK"
        if is_overfit:
            overfit_count += 1

        is_pf_str = f"{is_r.profit_factor:.2f}" if is_r.profit_factor < 100 else "INF"
        oos_pf_str = f"{oos_r.profit_factor:.2f}" if oos_r.profit_factor < 100 else "INF"

        print(
            f"{sym:<12} │ {is_r.win_rate*100:>6.1f}% {is_pf_str:>7} {is_r.avg_pnl_bps:>+8.1f} │ "
            f"{oos_r.win_rate*100:>6.1f}% {oos_pf_str:>7} {oos_r.avg_pnl_bps:>+8.1f} │ "
            f"{wr_diff:>+7.1f}% {pf_ratio:>8.2f} {verdict:>10}"
        )

    print("-" * 110)
    print(f"  Overfit symbols: {overfit_count}/{total}  |  "
          f"Criteria: OOS_PF < 50% of IS_PF or OOS_WR < IS_WR - 15%p")
    print()


def main():
    parser = argparse.ArgumentParser(description="1h 375d × 20coin 전면 백테스트")
    parser.add_argument("--skip-download", action="store_true", help="캐시 데이터만 사용")
    parser.add_argument("--data-dir", type=str, default=str(PROJECT_ROOT / "quant_runtime" / "backtest_1h_data"))
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Data ──
    print(f"\n[1/4] Loading 1h klines ({DAYS}d × {len(UNIVERSE)} coins)")
    print(f"  Data dir: {data_dir}")
    if args.skip_download:
        dfs = load_cached_data(UNIVERSE, data_dir)
        print(f"  Loaded {len(dfs)} cached symbols")
    else:
        dfs = download_1h_klines(UNIVERSE, DAYS, data_dir)
        print(f"  Downloaded/cached {len(dfs)} symbols")

    if not dfs:
        print("ERROR: No data available. Run without --skip-download first.")
        sys.exit(1)

    # ── 2. Split IS/OOS ──
    print(f"\n[2/4] Splitting In-Sample(75%) / Out-of-Sample(25%)")

    is_results: list[CoinResult] = []
    oos_results: list[CoinResult] = []
    full_results: list[CoinResult] = []

    for sym, df in sorted(dfs.items()):
        profile = get_profile(sym)
        n = len(df)
        split_idx = int(n * 0.75)

        df_is = df.iloc[:split_idx].reset_index(drop=True)
        df_oos = df.iloc[split_idx:].reset_index(drop=True)

        is_start = pd.Timestamp(df_is["timestamp"].iloc[0], unit="ms").strftime("%Y-%m-%d")
        is_end = pd.Timestamp(df_is["timestamp"].iloc[-1], unit="ms").strftime("%Y-%m-%d")
        oos_start = pd.Timestamp(df_oos["timestamp"].iloc[0], unit="ms").strftime("%Y-%m-%d")
        oos_end = pd.Timestamp(df_oos["timestamp"].iloc[-1], unit="ms").strftime("%Y-%m-%d")
        print(f"  {sym:<12} total={n:>5}  IS={len(df_is):>5} ({is_start}~{is_end})  "
              f"OOS={len(df_oos):>5} ({oos_start}~{oos_end})  "
              f"profile={'custom' if sym in COIN_PROFILES else 'default'}")

        # ── 3. Signals & Trades ──
        for label, sub_df in [("IS", df_is), ("OOS", df_oos), ("FULL", df)]:
            signals = generate_signals(sub_df, profile)
            trades = simulate_trades(sub_df, signals, sym)
            result = compute_metrics(trades, sym, label)

            if label == "IS":
                is_results.append(result)
            elif label == "OOS":
                oos_results.append(result)
            else:
                full_results.append(result)

    # ── 4. Results ──
    print(f"\n[3/4] Computing metrics")
    print(f"  Cost assumption: {COST_BPS} bps round-trip")

    print_results_table(full_results, f"FULL PERIOD ({DAYS}d) — All Coins")
    print_results_table(is_results, "IN-SAMPLE (75%) — Training Period")
    print_results_table(oos_results, "OUT-OF-SAMPLE (25%) — Validation Period")

    # ── 5. Overfit Check ──
    print(f"\n[4/4] Overfitting validation")
    print_overfit_comparison(is_results, oos_results)

    # ── Summary ──
    profiled = [r for r in full_results if r.symbol in COIN_PROFILES]
    default = [r for r in full_results if r.symbol not in COIN_PROFILES]

    print("=" * 80)
    print("  SUMMARY")
    print("=" * 80)
    if profiled:
        avg_pf = np.mean([r.profit_factor for r in profiled if r.profit_factor < 100])
        avg_wr = np.mean([r.win_rate for r in profiled]) * 100
        print(f"  Profiled coins ({len(profiled)}): avg PF={avg_pf:.2f}, avg WR={avg_wr:.1f}%")
    if default:
        avg_pf = np.mean([r.profit_factor for r in default if r.profit_factor < 100 and r.n_trades > 0])
        avg_wr = np.mean([r.win_rate for r in default if r.n_trades > 0]) * 100
        print(f"  Default coins ({len(default)}):  avg PF={avg_pf:.2f}, avg WR={avg_wr:.1f}%")

    # OOS degradation
    oos_pass = sum(1 for r in oos_results if r.profit_factor >= 1.0 and r.n_trades > 0)
    oos_total = sum(1 for r in oos_results if r.n_trades > 0)
    print(f"  OOS profitable: {oos_pass}/{oos_total} coins (PF >= 1.0)")
    print()


if __name__ == "__main__":
    main()
