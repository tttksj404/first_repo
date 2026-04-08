#!/usr/bin/env python3
"""
B3 Market Structure Break (MSB) 전략 파라미터 그리드서치 최적화
- 4심볼 (BTC/ETH/SOL/XRP) × 90일 1h 데이터
- 432가지 파라미터 조합 테스트
- PF ≥ 1.5 & 거래수 ≥ 15 조합 필터링
- 결과를 strategy_override.approved.json 에 반영
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import numpy as np

# ── 상수 ─────────────────────────────────────────────────────────────────────
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
INTERVAL = "1h"          # 1시간봉 (MSB 에 적합)
LOOKBACK_DAYS = 90       # 데이터 조회 기간

# 왕복 비용: 수수료 0.12% + 슬리피지 0.05% = 0.17%
ROUND_TRIP_COST = 0.0017

# 그리드서치 파라미터
SWING_WINDOWS           = [10, 15, 20, 30]
ATR_TP_MULTIPLES        = [2.0, 2.5, 3.0, 4.0]
BREAKOUT_CONFIRMATIONS  = [0.0, 0.1, 0.2]      # 돌파 버퍼 (%)
TREND_FILTERS           = [None, "ema50_slope", "adx20"]
MIN_SWING_SIZES         = [0.5, 1.0, 1.5]       # 최소 스윙 크기 (ATR 배수)

REPO_ROOT    = Path(__file__).resolve().parent.parent
CACHE_DIR    = REPO_ROOT / "quant_runtime" / "artifacts" / "b3_cache"
OVERRIDE_JSON = REPO_ROOT / "quant_runtime" / "artifacts" / "strategy_override.approved.json"


# ── 데이터 수집 ───────────────────────────────────────────────────────────────

def _interval_ms(interval: str) -> int:
    """인터벌 문자열 → 밀리초"""
    if interval.endswith("m"):
        return int(interval[:-1]) * 60_000
    if interval.endswith("h"):
        return int(interval[:-1]) * 3_600_000
    if interval.endswith("d"):
        return int(interval[:-1]) * 86_400_000
    return 3_600_000


def _fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    """바이낸스 Futures REST API 에서 OHLCV 수집 (페이징 처리)"""
    base = "https://fapi.binance.com/fapi/v1/klines"
    bars: list = []
    cur = start_ms
    step = _interval_ms(interval)

    while cur < end_ms:
        qs = urllib.parse.urlencode({
            "symbol": symbol, "interval": interval,
            "startTime": cur, "endTime": end_ms, "limit": 1000,
        })
        try:
            with urllib.request.urlopen(f"{base}?{qs}", timeout=20) as r:
                batch = json.loads(r.read())
        except urllib.error.URLError as exc:
            print(f"  [오류] {symbol} 수집 실패: {exc} — 3초 후 재시도")
            time.sleep(3)
            continue

        if not batch:
            break
        bars.extend(batch)
        cur = int(batch[-1][0]) + step
        if len(batch) < 1000:
            break
        time.sleep(0.08)

    return bars


def _to_arrays(bars: list) -> dict[str, np.ndarray]:
    arr = np.array(
        [[float(b[1]), float(b[2]), float(b[3]), float(b[4])] for b in bars],
        dtype=np.float64,
    )
    return {"open": arr[:, 0], "high": arr[:, 1], "low": arr[:, 2], "close": arr[:, 3]}


def load_ohlcv(symbol: str, days: int = LOOKBACK_DAYS) -> dict[str, np.ndarray]:
    """캐시 우선 로드 (1시간 이내 캐시 유효), 없으면 API 수집"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{symbol}_{INTERVAL}_{days}d.json"
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - days * 86_400_000

    if cache.exists():
        age_h = (now_ms / 1000 - cache.stat().st_mtime) / 3600
        if age_h < 1.0:
            with open(cache) as f:
                bars = json.load(f)
            print(f"  {symbol}: 캐시 로드 ({len(bars)}봉)")
            return _to_arrays(bars)

    print(f"  {symbol}: API 수집 중...", end="", flush=True)
    bars = _fetch_klines(symbol, INTERVAL, start_ms, now_ms)
    with open(cache, "w") as f:
        json.dump(bars, f)
    print(f" {len(bars)}봉 완료")
    return _to_arrays(bars)


# ── 지표 계산 (사전 계산용) ───────────────────────────────────────────────────

def calc_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    n = len(close)
    tr = np.zeros(n)
    tr[1:] = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
    )
    atr = np.zeros(n)
    if n <= period:
        return atr
    atr[period] = tr[1 : period + 1].mean()
    alpha = 1.0 / period
    for i in range(period + 1, n):
        atr[i] = atr[i - 1] * (1 - alpha) + tr[i] * alpha
    return atr


def calc_ema(close: np.ndarray, period: int) -> np.ndarray:
    n = len(close)
    ema = np.zeros(n)
    if n < period:
        return ema
    ema[period - 1] = close[:period].mean()
    k = 2.0 / (period + 1)
    for i in range(period, n):
        ema[i] = close[i] * k + ema[i - 1] * (1 - k)
    return ema


def calc_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 20) -> np.ndarray:
    n = len(close)
    adx = np.zeros(n)
    if n < period * 2 + 2:
        return adx

    pdm = np.zeros(n)
    mdm = np.zeros(n)
    tr  = np.zeros(n)
    for i in range(1, n):
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i]  = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    # Wilder 평활화
    atr_w = np.zeros(n); pdm_w = np.zeros(n); mdm_w = np.zeros(n)
    atr_w[period] = tr[1 : period + 1].sum()
    pdm_w[period] = pdm[1 : period + 1].sum()
    mdm_w[period] = mdm[1 : period + 1].sum()
    for i in range(period + 1, n):
        atr_w[i] = atr_w[i - 1] - atr_w[i - 1] / period + tr[i]
        pdm_w[i] = pdm_w[i - 1] - pdm_w[i - 1] / period + pdm[i]
        mdm_w[i] = mdm_w[i - 1] - mdm_w[i - 1] / period + mdm[i]

    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = np.where(atr_w > 0, 100 * pdm_w / atr_w, 0.0)
        mdi = np.where(atr_w > 0, 100 * mdm_w / atr_w, 0.0)
        denom = pdi + mdi
        dx = np.where(denom > 0, 100 * np.abs(pdi - mdi) / denom, 0.0)

    adx[2 * period] = dx[period : 2 * period + 1].mean()
    alpha = 1.0 / period
    for i in range(2 * period + 1, n):
        adx[i] = adx[i - 1] * (1 - alpha) + dx[i] * alpha

    return adx


def precompute_indicators(ohlcv: dict) -> dict:
    """각 심볼에 대해 ATR14, EMA50 기울기, ADX20 사전 계산"""
    h, l, c = ohlcv["high"], ohlcv["low"], ohlcv["close"]
    atr14 = calc_atr(h, l, c, 14)
    ema50 = calc_ema(c, 50)
    # EMA 기울기 (부호만 사용): 양수=상승, 음수=하락
    ema50_slope = np.zeros(len(c))
    ema50_slope[1:] = ema50[1:] - ema50[:-1]
    adx20 = calc_adx(h, l, c, 20)
    return {"atr14": atr14, "ema50_slope": ema50_slope, "adx20": adx20}


# ── 백테스트 엔진 ──────────────────────────────────────────────────────────────

def backtest_b3(
    ohlcv: dict[str, np.ndarray],
    indic: dict[str, np.ndarray],
    swing_window: int,
    atr_tp_mult: float,
    breakout_buf_pct: float,
    trend_filter: str | None,
    min_swing_atr: float,
) -> dict:
    """B3 MSB 전략 단일 백테스트 → 집계 지표 반환"""
    high  = ohlcv["high"]
    low   = ohlcv["low"]
    close = ohlcv["close"]
    atr14       = indic["atr14"]
    ema50_slope = indic["ema50_slope"]
    adx20       = indic["adx20"]
    n = len(close)

    # 워밍업: 지표 안정화를 위해 충분한 선두 봉 스킵
    warmup = max(swing_window + 20, 55)
    if trend_filter == "adx20":
        warmup = max(warmup, 45)

    in_pos   = False
    side     = ""         # "long" | "short"
    entry_px = 0.0
    sl_px    = 0.0
    tp_px    = 0.0

    gross_profit = 0.0   # 이익 합 (소수점 수익률)
    gross_loss   = 0.0   # 손실 합 (절댓값)
    n_wins  = 0
    n_total = 0
    equity  = 1.0
    peak    = 1.0
    max_dd  = 0.0

    for i in range(warmup, n):
        cur_atr = atr14[i]
        if cur_atr <= 0:
            continue

        # ── 포지션 관리: SL / TP 체크 ──────────────────────────────────────
        if in_pos:
            if side == "long":
                if low[i] <= sl_px:
                    pnl = (sl_px / entry_px - 1.0) - ROUND_TRIP_COST
                elif high[i] >= tp_px:
                    pnl = (tp_px / entry_px - 1.0) - ROUND_TRIP_COST
                else:
                    # 포지션 유지
                    peak = max(peak, equity)
                    dd = (equity - peak) / peak
                    max_dd = min(max_dd, dd)
                    continue

            else:  # short
                if high[i] >= sl_px:
                    pnl = (entry_px / sl_px - 1.0) - ROUND_TRIP_COST
                elif low[i] <= tp_px:
                    pnl = (entry_px / tp_px - 1.0) - ROUND_TRIP_COST
                else:
                    peak = max(peak, equity)
                    dd = (equity - peak) / peak
                    max_dd = min(max_dd, dd)
                    continue

            # 거래 종료
            equity *= (1.0 + pnl)
            n_total += 1
            if pnl > 0:
                gross_profit += pnl
                n_wins += 1
            else:
                gross_loss += abs(pnl)
            peak = max(peak, equity)
            dd = (equity - peak) / peak
            max_dd = min(max_dd, dd)
            in_pos = False

        # ── 신호 탐지 ───────────────────────────────────────────────────────
        sw_high = float(np.max(high[i - swing_window : i]))
        sw_low  = float(np.min(low[i - swing_window : i]))
        sw_range = sw_high - sw_low

        # 최소 스윙 크기 필터
        if sw_range < min_swing_atr * cur_atr:
            continue

        buf = breakout_buf_pct / 100.0
        c_close = close[i]

        long_sig  = c_close > sw_high * (1.0 + buf)
        short_sig = c_close < sw_low  * (1.0 - buf)

        # 추세 필터 적용
        if trend_filter == "ema50_slope":
            if long_sig  and ema50_slope[i] <= 0:
                long_sig  = False
            if short_sig and ema50_slope[i] >= 0:
                short_sig = False
        elif trend_filter == "adx20":
            if adx20[i] < 25.0:
                long_sig  = False
                short_sig = False

        # 진입 조건 확인 (동시 신호 → 무시)
        if long_sig and not short_sig:
            ep = c_close
            sl = sw_low
            if ep <= sl:          # SL이 진입가보다 높은 비정상 케이스
                continue
            tp = ep + atr_tp_mult * cur_atr
            in_pos = True; side = "long"
            entry_px = ep; sl_px = sl; tp_px = tp

        elif short_sig and not long_sig:
            ep = c_close
            sl = sw_high
            if ep >= sl:          # SL이 진입가보다 낮은 비정상 케이스
                continue
            tp = ep - atr_tp_mult * cur_atr
            in_pos = True; side = "short"
            entry_px = ep; sl_px = sl; tp_px = tp

    # ── 결과 집계 ────────────────────────────────────────────────────────────
    if n_total == 0:
        return {"pf": 0.0, "win_rate": 0.0, "n_trades": 0, "mdd": 0.0,
                "gross_profit": 0.0, "gross_loss": 0.0}

    pf = (gross_profit / gross_loss) if gross_loss > 1e-12 else (999.0 if gross_profit > 0 else 0.0)
    wr = n_wins / n_total * 100.0

    return {
        "pf":           round(float(pf), 4),
        "win_rate":     round(float(wr), 1),
        "n_trades":     n_total,
        "mdd":          round(float(max_dd * 100), 1),
        "gross_profit": gross_profit,
        "gross_loss":   gross_loss,
    }


# ── 그리드서치 ────────────────────────────────────────────────────────────────

def run_grid_search(
    data: dict[str, dict],
    indicators: dict[str, dict],
) -> list[dict]:
    """432가지 조합 × 4심볼 백테스트 실행"""
    combos = list(product(
        SWING_WINDOWS, ATR_TP_MULTIPLES, BREAKOUT_CONFIRMATIONS,
        TREND_FILTERS, MIN_SWING_SIZES,
    ))
    total = len(combos)
    print(f"\n그리드서치 시작: {total}가지 조합 × {len(SYMBOLS)}심볼 = {total * len(SYMBOLS):,}회 백테스트")

    aggregated: list[dict] = []

    for idx, (sw, tp_m, buf, filt, ms) in enumerate(combos):
        if (idx + 1) % 72 == 0:
            pct = (idx + 1) / total * 100
            print(f"  진행: {idx+1}/{total} ({pct:.0f}%)")

        sym_results: dict[str, dict] = {}
        total_gp = total_gl = 0.0
        total_trades = 0
        win_rates: list[float] = []
        mdds: list[float] = []

        for sym in SYMBOLS:
            m = backtest_b3(
                data[sym], indicators[sym],
                swing_window=sw, atr_tp_mult=tp_m,
                breakout_buf_pct=buf, trend_filter=filt,
                min_swing_atr=ms,
            )
            sym_results[sym] = m
            total_gp     += m["gross_profit"]
            total_gl     += m["gross_loss"]
            total_trades += m["n_trades"]
            if m["n_trades"] > 0:
                win_rates.append(m["win_rate"])
                mdds.append(m["mdd"])

        # 통합 PF: 전체 GP / GL (가중 정확 집계)
        if total_gl > 1e-12:
            comb_pf = round(total_gp / total_gl, 4)
        elif total_gp > 0:
            comb_pf = 999.0
        else:
            comb_pf = 0.0

        avg_wr  = round(sum(win_rates) / len(win_rates), 1) if win_rates else 0.0
        avg_mdd = round(sum(mdds) / len(mdds), 1) if mdds else 0.0

        aggregated.append({
            "swing":      sw,
            "tp":         tp_m,
            "buf":        buf,
            "filter":     filt if filt else "none",
            "min_swing":  ms,
            "pf":         comb_pf,
            "win_rate":   avg_wr,
            "n_trades":   total_trades,
            "mdd":        avg_mdd,
            "sym":        sym_results,
        })

    aggregated.sort(key=lambda x: x["pf"], reverse=True)
    return aggregated


# ── 출력 및 반영 ──────────────────────────────────────────────────────────────

def _fmt(r: dict) -> str:
    filt = r["filter"] if r["filter"] != "none" else "없음"
    return (
        f"swing={r['swing']:2d}, tp={r['tp']:.1f}x, buf={r['buf']:.1f}%, "
        f"filter={filt:<11s}, min_swing={r['min_swing']:.1f} "
        f"→ PF={r['pf']:.2f}, 승률={r['win_rate']:.0f}%, "
        f"거래수={r['n_trades']}, MDD={r['mdd']:.1f}%"
    )


def print_results(results: list[dict]) -> tuple[bool, list[dict]]:
    """결과 출력 및 달성 여부 반환"""
    qualified = [r for r in results if r["n_trades"] >= 15 and r["pf"] >= 1.5]
    # already sorted by PF desc from run_grid_search

    print("\n" + "=" * 72)
    print("TOP 조합 (PF ≥ 1.5, 거래수 ≥ 15):")
    if not qualified:
        print("  없음 — PF ≥ 1.5 달성 조합 발견하지 못함")
    else:
        for rank, r in enumerate(qualified[:20], 1):
            print(f"{rank:3d}. {_fmt(r)}")

    print("\n심볼별 최고 조합 (개별 PF 기준, 거래수 ≥ 5):")
    for sym in SYMBOLS:
        best_r = None
        best_pf = -1.0
        for r in results:
            sm = r["sym"][sym]
            if sm["n_trades"] >= 5 and sm["pf"] > best_pf:
                best_pf = sm["pf"]
                best_r  = (r, sm)
        sym_short = sym.replace("USDT", "")
        if best_r:
            r, sm = best_r
            filt = r["filter"] if r["filter"] != "none" else "없음"
            print(
                f"  {sym_short:<4s}: swing={r['swing']:2d}, tp={r['tp']:.1f}x, "
                f"buf={r['buf']:.1f}%, filter={filt:<11s}, min_swing={r['min_swing']:.1f} "
                f"→ PF={sm['pf']:.2f}, 승률={sm['win_rate']:.0f}%, 거래수={sm['n_trades']}"
            )
        else:
            print(f"  {sym_short:<4s}: 유효 조합 없음")

    achieved = bool(qualified)
    print(f"\nPF ≥ 1.5 달성 여부: {'O' if achieved else 'X'}")
    print("=" * 72)
    return achieved, qualified


def update_override(best: dict) -> None:
    """최적 파라미터를 strategy_override.approved.json 에 반영"""
    if not OVERRIDE_JSON.exists():
        print(f"[경고] {OVERRIDE_JSON} 파일 없음 — 반영 건너뜀")
        return

    with open(OVERRIDE_JSON) as f:
        data = json.load(f)

    data["b3_msb_strategy"] = {
        "enabled":                   True,
        "optimized_at":              datetime.now(timezone.utc).isoformat(),
        "interval":                  INTERVAL,
        "lookback_days":             LOOKBACK_DAYS,
        "symbols":                   SYMBOLS,
        "swing_window":              best["swing"],
        "atr_tp_multiple":           best["tp"],
        "breakout_confirmation_pct": best["buf"],
        "trend_filter":              best["filter"],
        "min_swing_size_atr":        best["min_swing"],
        "backtest_pf":               best["pf"],
        "backtest_win_rate_pct":     best["win_rate"],
        "backtest_n_trades":         best["n_trades"],
        "note": "B3 MSB 그리드서치 자동 최적화 결과 (90일 1h)",
    }

    with open(OVERRIDE_JSON, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n최적 파라미터 → strategy_override.approved.json 반영 완료")
    print(f"  {_fmt(best)}")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    n_combos = (
        len(SWING_WINDOWS) * len(ATR_TP_MULTIPLES) *
        len(BREAKOUT_CONFIRMATIONS) * len(TREND_FILTERS) * len(MIN_SWING_SIZES)
    )
    print("=" * 72)
    print("B3 MSB 전략 파라미터 그리드서치 최적화")
    print(f"심볼  : {', '.join(SYMBOLS)}")
    print(f"기간  : {LOOKBACK_DAYS}일 ({INTERVAL} 캔들)")
    print(f"비용  : 수수료 0.12% + 슬리피지 0.05% = 왕복 {ROUND_TRIP_COST*100:.2f}%")
    print(f"조합수: {n_combos}가지 (4×4×3×3×3)")
    print("=" * 72)

    # 1. 데이터 수집
    print("\n[1/3] OHLCV 데이터 수집...")
    ohlcv_data: dict[str, dict] = {}
    for sym in SYMBOLS:
        ohlcv_data[sym] = load_ohlcv(sym)

    # 2. 지표 사전 계산 (ATR14, EMA50 기울기, ADX20)
    print("\n[2/3] 지표 사전 계산...")
    indicators: dict[str, dict] = {}
    for sym in SYMBOLS:
        indicators[sym] = precompute_indicators(ohlcv_data[sym])
        n_bars = len(ohlcv_data[sym]["close"])
        atr_ok = np.sum(indicators[sym]["atr14"] > 0)
        print(f"  {sym}: {n_bars}봉, ATR유효={atr_ok}봉")

    # 3. 그리드서치
    print("\n[3/3] 그리드서치 실행...")
    t0 = time.time()
    results = run_grid_search(ohlcv_data, indicators)
    elapsed = time.time() - t0
    print(f"완료: {elapsed:.1f}초")

    # 4. 결과 출력
    achieved, qualified = print_results(results)

    # 5. 최적 파라미터 반영
    if achieved:
        best = qualified[0]
        update_override(best)
        print("\n최적 파라미터 → strategy_override.approved.json 반영 여부: 반영됨")
    else:
        print("\n최적 파라미터 → strategy_override.approved.json 반영 여부: 미반영 (PF 기준 미달)")

    # 6. 전체 결과 저장 (Top 200)
    out_path = CACHE_DIR / "b3_grid_results.json"
    save_rows = []
    for r in results[:200]:
        row = {k: v for k, v in r.items() if k != "sym"}
        # 심볼별 요약도 포함 (gross_profit/loss 제외)
        row["sym_pf"] = {
            s: {"pf": m["pf"], "wr": m["win_rate"], "n": m["n_trades"]}
            for s, m in r["sym"].items()
        }
        save_rows.append(row)
    with open(out_path, "w") as f:
        json.dump(save_rows, f, indent=2, ensure_ascii=False)
    print(f"\n전체 결과 저장 (Top 200): {out_path}")


if __name__ == "__main__":
    main()
