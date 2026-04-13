#!/usr/bin/env python3
"""
B3 MSB 전략 Walk-Forward 검증
- 90일 데이터 → Train 60일 / Test 30일 분리
- 최적 파라미터 (swing=15, tp=4.0x, buf=0.1%, ADX≥25) 고정 사용
- 4심볼 (BTC/ETH/SOL/XRP) 각각 비교
- 수수료 0.12% + 슬리피지 0.05% 왕복 적용
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# ── 설정 ─────────────────────────────────────────────────────────────────────
SYMBOLS       = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
INTERVAL      = "1h"
TOTAL_DAYS    = 90
TRAIN_DAYS    = 60
TEST_DAYS     = 30

# 최적 파라미터 (그리드서치 결과)
BEST_PARAMS = {
    "swing_window":  15,
    "atr_tp_mult":   4.0,
    "breakout_buf":  0.1,    # %
    "adx_min":       25.0,   # ADX 최소값
    "min_swing_atr": 0.5,
}

ROUND_TRIP_COST = 0.0017  # 수수료 0.12% + 슬리피지 0.05%

REPO_ROOT  = Path(__file__).resolve().parent.parent
CACHE_DIR  = REPO_ROOT / "quant_runtime" / "artifacts" / "b3_cache"


# ── 데이터 로드 (캐시 우선) ───────────────────────────────────────────────────

def _interval_ms(interval: str) -> int:
    if interval.endswith("m"): return int(interval[:-1]) * 60_000
    if interval.endswith("h"): return int(interval[:-1]) * 3_600_000
    if interval.endswith("d"): return int(interval[:-1]) * 86_400_000
    return 3_600_000


def _fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
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
            print(f"  [재시도] {symbol}: {exc}")
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


def load_ohlcv(symbol: str) -> dict[str, np.ndarray]:
    cache = CACHE_DIR / f"{symbol}_{INTERVAL}_{TOTAL_DAYS}d.json"
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - TOTAL_DAYS * 86_400_000

    if cache.exists():
        with open(cache) as f:
            bars = json.load(f)
        age_h = (now_ms / 1000 - cache.stat().st_mtime) / 3600
        print(f"  {symbol}: 캐시 로드 ({len(bars)}봉, {age_h:.0f}시간 전)")
        return _to_arrays(bars)

    print(f"  {symbol}: API 수집...", end="", flush=True)
    bars = _fetch_klines(symbol, INTERVAL, start_ms, now_ms)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache, "w") as f:
        json.dump(bars, f)
    print(f" {len(bars)}봉")
    return _to_arrays(bars)


def _to_arrays(bars: list) -> dict[str, np.ndarray]:
    arr = np.array([[float(b[1]), float(b[2]), float(b[3]), float(b[4])] for b in bars], dtype=np.float64)
    return {"open": arr[:, 0], "high": arr[:, 1], "low": arr[:, 2], "close": arr[:, 3]}


# ── 지표 계산 ────────────────────────────────────────────────────────────────

def calc_atr(h, l, c, period=14):
    n = len(c)
    tr = np.zeros(n)
    tr[1:] = np.maximum(h[1:]-l[1:], np.maximum(np.abs(h[1:]-c[:-1]), np.abs(l[1:]-c[:-1])))
    atr = np.zeros(n)
    if n <= period: return atr
    atr[period] = tr[1:period+1].mean()
    a = 1.0 / period
    for i in range(period+1, n):
        atr[i] = atr[i-1]*(1-a) + tr[i]*a
    return atr


def calc_adx(h, l, c, period=20):
    n = len(c)
    adx = np.zeros(n)
    if n < period*2+2: return adx
    pdm = np.zeros(n); mdm = np.zeros(n); tr = np.zeros(n)
    for i in range(1, n):
        up = h[i]-h[i-1]; dn = l[i-1]-l[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    aw = np.zeros(n); pw = np.zeros(n); mw = np.zeros(n)
    aw[period] = tr[1:period+1].sum()
    pw[period] = pdm[1:period+1].sum()
    mw[period] = mdm[1:period+1].sum()
    for i in range(period+1, n):
        aw[i] = aw[i-1] - aw[i-1]/period + tr[i]
        pw[i] = pw[i-1] - pw[i-1]/period + pdm[i]
        mw[i] = mw[i-1] - mw[i-1]/period + mdm[i]
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = np.where(aw>0, 100*pw/aw, 0.0)
        mdi = np.where(aw>0, 100*mw/aw, 0.0)
        denom = pdi+mdi
        dx = np.where(denom>0, 100*np.abs(pdi-mdi)/denom, 0.0)
    adx[2*period] = dx[period:2*period+1].mean()
    a = 1.0/period
    for i in range(2*period+1, n):
        adx[i] = adx[i-1]*(1-a) + dx[i]*a
    return adx


# ── 백테스트 엔진 ─────────────────────────────────────────────────────────────

def backtest(
    h: np.ndarray, l: np.ndarray, c: np.ndarray,
    atr14: np.ndarray, adx20: np.ndarray,
    sw: int, tp_m: float, buf_pct: float, adx_min: float, ms: float,
    warmup: int,
) -> dict:
    n = len(c)
    in_pos = False; side = ""; ep = sl = tp = 0.0
    gp = gl = 0.0; n_wins = n_total = 0
    equity = 1.0; peak = 1.0; max_dd = 0.0

    for i in range(warmup, n):
        cur_atr = atr14[i]
        if cur_atr <= 0: continue

        if in_pos:
            if side == "long":
                if l[i] <= sl:
                    pnl = (sl/ep - 1.0) - ROUND_TRIP_COST
                elif h[i] >= tp:
                    pnl = (tp/ep - 1.0) - ROUND_TRIP_COST
                else:
                    peak = max(peak, equity); max_dd = min(max_dd, (equity-peak)/peak)
                    continue
            else:
                if h[i] >= sl:
                    pnl = (ep/sl - 1.0) - ROUND_TRIP_COST
                elif l[i] <= tp:
                    pnl = (ep/tp - 1.0) - ROUND_TRIP_COST
                else:
                    peak = max(peak, equity); max_dd = min(max_dd, (equity-peak)/peak)
                    continue
            equity *= (1+pnl); n_total += 1
            if pnl > 0: gp += pnl; n_wins += 1
            else: gl += abs(pnl)
            peak = max(peak, equity); max_dd = min(max_dd, (equity-peak)/peak)
            in_pos = False

        # 신호
        if adx20[i] < adx_min: continue
        sw_h = float(np.max(h[i-sw:i]))
        sw_l = float(np.min(l[i-sw:i]))
        sw_range = sw_h - sw_l
        if sw_range < ms * cur_atr: continue

        buf = buf_pct / 100.0
        long_sig  = c[i] > sw_h * (1+buf)
        short_sig = c[i] < sw_l * (1-buf)

        if long_sig and not short_sig:
            ep_p = c[i]; sl_p = sw_l
            if ep_p <= sl_p: continue
            ep=ep_p; sl=sl_p; tp=ep_p + tp_m*cur_atr
            in_pos=True; side="long"
        elif short_sig and not long_sig:
            ep_p = c[i]; sl_p = sw_h
            if ep_p >= sl_p: continue
            ep=ep_p; sl=sl_p; tp=ep_p - tp_m*cur_atr
            in_pos=True; side="short"

    if n_total == 0:
        return {"pf": 0.0, "wr": 0.0, "n": 0, "mdd": 0.0, "ret": 0.0, "gp": 0.0, "gl": 0.0}
    pf = (gp/gl) if gl > 1e-12 else (999.0 if gp > 0 else 0.0)
    return {
        "pf": round(pf, 3), "wr": round(n_wins/n_total*100, 1),
        "n": n_total, "mdd": round(max_dd*100, 1),
        "ret": round((equity-1)*100, 2), "gp": gp, "gl": gl,
    }


# ── Walk-Forward 실행 ─────────────────────────────────────────────────────────

def run_walkforward(data: dict[str, dict]) -> None:
    p = BEST_PARAMS
    sw, tp_m, buf, adx_min, ms = p["swing_window"], p["atr_tp_mult"], p["breakout_buf"], p["adx_min"], p["min_swing_atr"]
    warmup = max(sw + 20, 45)

    print(f"\n최적 파라미터: swing={sw}, tp={tp_m}x, buf={buf}%, ADX≥{adx_min}, min_swing={ms}x ATR")
    print(f"비용: 왕복 {ROUND_TRIP_COST*100:.2f}% (수수료 0.12% + 슬리피지 0.05%)")
    print(f"분리: Train={TRAIN_DAYS}일 / Test={TEST_DAYS}일\n")
    print(f"{'심볼':<8} {'구간':<6} {'PF':>6} {'승률':>6} {'거래수':>6} {'수익률':>8} {'MDD':>8}")
    print("-" * 55)

    all_train_gp = all_train_gl = 0.0
    all_test_gp  = all_test_gl  = 0.0
    all_train_n  = all_test_n   = 0

    per_sym: dict[str, dict] = {}

    for sym in SYMBOLS:
        ohlcv = data[sym]
        h, l, c = ohlcv["high"], ohlcv["low"], ohlcv["close"]
        n = len(c)

        atr14 = calc_atr(h, l, c, 14)
        adx20 = calc_adx(h, l, c, 20)

        # 분리 인덱스 (1h 봉 기준: 24봉/일)
        bars_per_day = 24
        train_end = int(n * TRAIN_DAYS / TOTAL_DAYS)
        # test는 마지막 30일
        test_start = n - TEST_DAYS * bars_per_day
        test_start = max(test_start, warmup)

        # Train 구간
        h_tr = h[:train_end]; l_tr = l[:train_end]; c_tr = c[:train_end]
        atr_tr = atr14[:train_end]; adx_tr = adx20[:train_end]
        tr_res = backtest(h_tr, l_tr, c_tr, atr_tr, adx_tr, sw, tp_m, buf, adx_min, ms, warmup)

        # Test 구간 (지표는 전체 데이터 기반으로 계산된 것 사용 — 룩어헤드 방지를 위해 slice)
        h_te = h[test_start:]; l_te = l[test_start:]; c_te = c[test_start:]
        atr_te = atr14[test_start:]; adx_te = adx20[test_start:]
        # test 구간 내 워밍업
        te_warmup = min(warmup, len(h_te) - 1)
        te_res = backtest(h_te, l_te, c_te, atr_te, adx_te, sw, tp_m, buf, adx_min, ms, te_warmup)

        sym_s = sym.replace("USDT", "")
        print(f"{sym_s:<8} {'Train':<6} {tr_res['pf']:>6.2f} {tr_res['wr']:>5.0f}% {tr_res['n']:>6} {tr_res['ret']:>7.1f}% {tr_res['mdd']:>7.1f}%")
        print(f"{'':<8} {'Test':<6} {te_res['pf']:>6.2f} {te_res['wr']:>5.0f}% {te_res['n']:>6} {te_res['ret']:>7.1f}% {te_res['mdd']:>7.1f}%")

        # 과최적화 경고
        if tr_res['pf'] > 0 and te_res['pf'] > 0:
            ratio = te_res['pf'] / tr_res['pf']
            flag = "✓" if ratio >= 0.7 else "△ (성과 하락)"
            print(f"{'':<8} {'':6} Test/Train PF 비율: {ratio:.2f} {flag}")
        elif te_res['n'] == 0:
            print(f"{'':<8} {'':6} [경고] Test 구간 거래 없음")
        print()

        per_sym[sym] = {"train": tr_res, "test": te_res}
        all_train_gp += tr_res["gp"]; all_train_gl += tr_res["gl"]; all_train_n += tr_res["n"]
        all_test_gp  += te_res["gp"]; all_test_gl  += te_res["gl"]; all_test_n  += te_res["n"]

    # 통합 요약
    print("=" * 55)
    comb_tr_pf = (all_train_gp/all_train_gl) if all_train_gl > 1e-12 else 0.0
    comb_te_pf = (all_test_gp/all_test_gl)   if all_test_gl  > 1e-12 else 0.0

    print(f"{'4심볼 통합':<8} {'Train':<6} PF={comb_tr_pf:.2f}, 거래수={all_train_n}")
    print(f"{'':8} {'Test':<6} PF={comb_te_pf:.2f}, 거래수={all_test_n}")

    if comb_tr_pf > 0 and comb_te_pf > 0:
        ratio = comb_te_pf / comb_tr_pf
        verdict = "PASS ✓" if comb_te_pf >= 1.2 and ratio >= 0.6 else "FAIL ✗"
        print(f"\nWalk-Forward 통과 기준 (Test PF ≥ 1.2 & 비율 ≥ 0.6): {verdict}")
        print(f"  Test PF={comb_te_pf:.2f}, Train PF={comb_tr_pf:.2f}, 비율={ratio:.2f}")
    else:
        print("\nWalk-Forward: 판단 불가 (거래 부족)")

    # 결과 저장
    out = {
        "params": BEST_PARAMS,
        "train_days": TRAIN_DAYS,
        "test_days": TEST_DAYS,
        "interval": INTERVAL,
        "symbols": SYMBOLS,
        "combined": {
            "train_pf": round(comb_tr_pf, 3),
            "test_pf":  round(comb_te_pf, 3),
            "train_n":  all_train_n,
            "test_n":   all_test_n,
        },
        "per_symbol": {
            sym: {"train": v["train"], "test": v["test"]}
            for sym, v in per_sym.items()
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    out_path = REPO_ROOT / "quant_runtime" / "artifacts" / "b3_cache" / "b3_walkforward_result.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n결과 저장: {out_path}")


# ── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("B3 MSB Walk-Forward 검증")
    print(f"Train {TRAIN_DAYS}일 / Test {TEST_DAYS}일 | {INTERVAL} 캔들 | 4심볼")
    print("=" * 55)
    print("\n데이터 로드...")
    data = {sym: load_ohlcv(sym) for sym in SYMBOLS}
    run_walkforward(data)


if __name__ == "__main__":
    main()
