"""
소자본 한탕 전략 대규모 백테스트 (A1~A7)
수수료 0.12% + 슬리피지 0.05% 왕복 반영
BTC/ETH/SOL/XRP, 90일, 1h
"""

import json
import os
import time
import math
import datetime
import requests
import numpy as np
import pandas as pd
from collections import defaultdict

# ─── 설정 ─────────────────────────────────────────────────────────────────────
SYMBOLS     = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
DAYS        = 90
INTERVAL    = "1h"
FEE_RT      = 0.0012   # 편도 수수료
SLIP_RT     = 0.0005   # 편도 슬리피지
COST_ONE_WAY = FEE_RT + SLIP_RT   # 편도 비용
COST_TOTAL   = COST_ONE_WAY * 2   # 왕복 총 비용

HIST_DIR    = "/Users/tttksj/first_repo/quant_runtime/historical"

# 평가 기준
MIN_PF     = 1.5
MIN_TRADES = 15
MIN_WR     = 0.40
MIN_RR     = 2.5


# ─── 데이터 로드 ──────────────────────────────────────────────────────────────
def load_local(symbol: str):
    path = os.path.join(HIST_DIR, symbol, "1h.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df.rename(columns={
        "open_time":    "ts",
        "open_price":   "open",
        "high_price":   "high",
        "low_price":    "low",
        "close_price":  "close",
        "base_volume":  "volume",
    }, inplace=True)
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df[["ts","open","high","low","close","volume"]].astype(
        {"open": float, "high": float, "low": float, "close": float, "volume": float}
    ).set_index("ts").sort_index()
    return df


def fetch_binance(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Binance Futures 1h OHLCV 페치 (1000봉씩)"""
    url = "https://fapi.binance.com/fapi/v1/klines"
    rows = []
    cur = start_ms
    while cur < end_ms:
        params = {
            "symbol":    symbol,
            "interval":  "1h",
            "startTime": cur,
            "endTime":   end_ms,
            "limit":     1000,
        }
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            batch = r.json()
        except Exception as e:
            print(f"  [fetch] {symbol} 오류: {e}")
            break
        if not batch:
            break
        rows.extend(batch)
        cur = batch[-1][0] + 3_600_000
        if len(batch) < 1000:
            break
        time.sleep(0.2)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=[
        "ts","open","high","low","close","volume",
        "close_time","qvol","ntrades","tb_base","tb_quote","ignore"
    ])
    df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
    df = df[["ts","open","high","low","close","volume"]].astype(
        {"open": float, "high": float, "low": float, "close": float, "volume": float}
    ).set_index("ts").sort_index()
    return df


def get_ohlcv(symbol: str) -> pd.DataFrame:
    end_dt   = datetime.datetime.now(datetime.timezone.utc)
    start_dt = end_dt - datetime.timedelta(days=DAYS)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp() * 1000)

    local = load_local(symbol)

    if local is not None and not local.empty:
        local_start = local.index[0]
        local_start_ms = int(local_start.timestamp() * 1000)
        if local_start_ms > start_ms:
            # 앞부분 API로 보충
            missing = fetch_binance(symbol, start_ms, local_start_ms)
            if not missing.empty:
                df = pd.concat([missing, local]).sort_index()
                df = df[~df.index.duplicated(keep="last")]
            else:
                df = local
        else:
            df = local
    else:
        df = fetch_binance(symbol, start_ms, end_ms)

    # 90일 범위로 자르기
    start_dt_pd = pd.Timestamp(start_dt)
    df = df[df.index >= start_dt_pd]
    print(f"  {symbol}: {len(df)}봉 ({df.index[0].date()} ~ {df.index[-1].date()})")
    return df


# ─── 지표 계산 ────────────────────────────────────────────────────────────────
def calc_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"]  - df["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def calc_rsi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain  = delta.clip(lower=0).rolling(n).mean()
    loss  = (-delta.clip(upper=0)).rolling(n).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def calc_bb(df: pd.DataFrame, n: int = 20) -> tuple:
    mid  = df["close"].rolling(n).mean()
    std  = df["close"].rolling(n).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    bw    = (upper - lower) / mid
    return upper, mid, lower, bw


def calc_vwap(df: pd.DataFrame) -> pd.Series:
    """일별 VWAP (00:00 UTC 리셋)"""
    tp     = (df["high"] + df["low"] + df["close"]) / 3
    day    = df.index.floor("D")
    cum_tv = (tp * df["volume"]).groupby(day).cumsum()
    cum_v  = df["volume"].groupby(day).cumsum()
    return cum_tv / cum_v


# ─── 공통 거래 실행 ───────────────────────────────────────────────────────────
def execute_trade(entry: float, direction: int, sl: float, tp: float,
                  future_closes: list) -> tuple:
    """
    direction: +1=long, -1=short
    future_closes: 진입 이후 봉들의 (high, low, close) 리스트
    returns: (pnl_pct, exit_reason)
    """
    for h, l, c in future_closes:
        if direction == 1:
            if l <= sl:
                gross = (sl - entry) / entry
                return gross - COST_TOTAL, "SL"
            if h >= tp:
                gross = (tp - entry) / entry
                return gross - COST_TOTAL, "TP"
        else:
            if h >= sl:
                gross = (entry - sl) / entry
                return gross - COST_TOTAL, "SL"
            if l <= tp:
                gross = (entry - tp) / entry
                return gross - COST_TOTAL, "TP"
    # 마지막 봉 종가로 강제 청산
    gross = direction * (future_closes[-1][2] - entry) / entry
    return gross - COST_TOTAL, "TIMEOUT"


def eval_results(pnls: list, trades_meta: list) -> dict:
    if len(pnls) < 1:
        return {"trades": 0, "pf": 0, "wr": 0, "avg_rr": 0, "total_pnl": 0}
    wins  = [p for p in pnls if p > 0]
    loses = [p for p in pnls if p < 0]
    gross_w = sum(wins)  if wins  else 0
    gross_l = sum(loses) if loses else 0
    pf  = gross_w / abs(gross_l) if gross_l != 0 else (float("inf") if gross_w > 0 else 0)
    wr  = len(wins) / len(pnls)
    avg_w  = np.mean(wins)  if wins  else 0
    avg_l  = abs(np.mean(loses)) if loses else 0
    avg_rr = avg_w / avg_l if avg_l > 0 else 0
    return {
        "trades":    len(pnls),
        "pf":        round(pf, 3),
        "wr":        round(wr, 4),
        "avg_rr":    round(avg_rr, 3),
        "total_pnl": round(sum(pnls) * 100, 2),  # %
        "wins":      len(wins),
        "losses":    len(loses),
    }


def future_bars(df: pd.DataFrame, i: int, n: int = 20) -> list:
    """인덱스 i 이후 n봉의 (high, low, close)"""
    end = min(i + 1 + n, len(df))
    return [(df["high"].iloc[j], df["low"].iloc[j], df["close"].iloc[j])
            for j in range(i + 1, end)]


# ─── 전략 A1: 연속 3봉 반전 ───────────────────────────────────────────────────
def strategy_a1(df: pd.DataFrame) -> dict:
    atr  = calc_atr(df)
    pnls = []
    warmup = 20
    i = warmup
    while i < len(df) - 1:
        a = atr.iloc[i]
        if pd.isna(a) or a == 0:
            i += 1; continue

        # 연속 3봉 이상 같은 방향 찾기
        streak = 1
        direction = 0
        for k in range(i, max(i - 6, warmup - 1), -1):
            body = df["close"].iloc[k] - df["open"].iloc[k]
            body_prev = df["close"].iloc[k-1] - df["open"].iloc[k-1]
            if abs(body) < a * 0.5:
                break
            if k == i:
                direction = 1 if body > 0 else -1
            elif (1 if body > 0 else -1) == direction and abs(body) >= a * 0.5:
                streak += 1
            else:
                break

        if streak < 3:
            i += 1; continue

        # 마지막 봉 거래량 감소 확인
        vol_cur  = df["volume"].iloc[i]
        vol_prev = df["volume"].iloc[i - 1]
        if vol_prev == 0 or vol_cur >= vol_prev * 0.70:
            i += 1; continue

        # 반전 진입
        entry     = df["close"].iloc[i]
        rev_dir   = -direction
        sl_dist   = a * 1.0
        tp_dist   = a * 2.5
        sl = entry + direction * sl_dist   # 반전이므로 기존 방향으로 손절
        tp = entry - direction * tp_dist   # 반전 방향으로 익절

        fb = future_bars(df, i, 20)
        if not fb:
            i += 1; continue

        pnl, reason = execute_trade(entry, rev_dir, sl, tp, fb)
        pnls.append(pnl)
        i += 1

    return eval_results(pnls, [])


# ─── 전략 A2: 이중 바닥/천장 ──────────────────────────────────────────────────
def strategy_a2(df: pd.DataFrame) -> dict:
    atr  = calc_atr(df)
    pnls = []
    warmup = 30

    i = warmup
    while i < len(df) - 2:
        a = atr.iloc[i]
        if pd.isna(a) or a == 0:
            i += 1; continue

        close_i = df["close"].iloc[i]

        # 이중 바닥: 최근 5~30봉 내에서 low가 현재 low의 ±0.5%
        cur_low = df["low"].iloc[i]
        found_db = False
        for j in range(i - 5, max(i - 30, warmup - 1), -1):
            prev_low = df["low"].iloc[j]
            if abs(prev_low - cur_low) / cur_low <= 0.005 and (i - j) >= 5:
                # 이중 바닥 패턴 높이
                pattern_high = df["high"].iloc[j:i+1].max()
                neck = pattern_high
                # 현재 봉이 neckline 돌파?
                if close_i > neck:
                    entry   = close_i
                    sl      = cur_low * (1 - 0.003)
                    height  = neck - cur_low
                    tp      = entry + height
                    fb = future_bars(df, i, 30)
                    if fb:
                        pnl, _ = execute_trade(entry, 1, sl, tp, fb)
                        pnls.append(pnl)
                    found_db = True
                    break

        if found_db:
            i += 1; continue

        # 이중 천장: 최근 5~30봉 내 high가 현재 high의 ±0.5%
        cur_high = df["high"].iloc[i]
        for j in range(i - 5, max(i - 30, warmup - 1), -1):
            prev_high = df["high"].iloc[j]
            if abs(prev_high - cur_high) / cur_high <= 0.005 and (i - j) >= 5:
                pattern_low = df["low"].iloc[j:i+1].min()
                neck = pattern_low
                if close_i < neck:
                    entry  = close_i
                    sl     = cur_high * (1 + 0.003)
                    height = cur_high - neck
                    tp     = entry - height
                    fb = future_bars(df, i, 30)
                    if fb:
                        pnl, _ = execute_trade(entry, -1, sl, tp, fb)
                        pnls.append(pnl)
                    break

        i += 1

    return eval_results(pnls, [])


# ─── 전략 A3: 강한 단일봉 모멘텀 추종 ────────────────────────────────────────
def strategy_a3(df: pd.DataFrame) -> dict:
    atr    = calc_atr(df)
    vol_ma = df["volume"].rolling(20).mean()
    pnls   = []
    warmup = 25

    i = warmup
    while i < len(df) - 1:
        a   = atr.iloc[i]
        vma = vol_ma.iloc[i]
        if pd.isna(a) or pd.isna(vma) or a == 0 or vma == 0:
            i += 1; continue

        body    = abs(df["close"].iloc[i] - df["open"].iloc[i])
        candle_size = df["high"].iloc[i] - df["low"].iloc[i]
        vol_cur = df["volume"].iloc[i]

        if candle_size < a * 2.5:
            i += 1; continue
        if vol_cur < vma * 2.0:
            i += 1; continue

        direction = 1 if df["close"].iloc[i] > df["open"].iloc[i] else -1
        entry     = df["close"].iloc[i]  # 다음 봉 시작 = 현재 봉 종가 근사
        sl_dist   = candle_size * 0.5
        tp_dist   = candle_size * 1.5
        sl = entry - direction * sl_dist
        tp = entry + direction * tp_dist

        fb = future_bars(df, i, 15)
        if not fb:
            i += 1; continue

        pnl, _ = execute_trade(entry, direction, sl, tp, fb)
        pnls.append(pnl)
        i += 1

    return eval_results(pnls, [])


# ─── 전략 A4: VWAP 이격 평균회귀 ─────────────────────────────────────────────
def strategy_a4(df: pd.DataFrame) -> dict:
    vwap = calc_vwap(df)
    pnls = []
    warmup = 5

    i = warmup
    while i < len(df) - 1:
        v = vwap.iloc[i]
        c = df["close"].iloc[i]
        if pd.isna(v) or v == 0:
            i += 1; continue

        dev = (c - v) / v  # 양수 = 위, 음수 = 아래

        if abs(dev) < 0.015:
            i += 1; continue

        # 이격이 1.5% 이상 → VWAP 쪽으로 회귀 진입
        direction = -1 if dev > 0 else 1  # 위에 있으면 short, 아래면 long
        entry   = c
        sl_dev  = 0.025
        sl      = entry * (1 + direction * (-sl_dev))   # 반대 방향으로 2.5% 더 벌어지면 손절
        tp_vwap = v
        # 0.5% 수익 or VWAP 도달
        tp_pct  = entry * (1 + direction * 0.005)
        tp      = tp_vwap if direction == 1 else max(tp_vwap, tp_pct) if direction == -1 else tp_pct
        # 방향 재정의
        if direction == 1:
            sl = entry * (1 - sl_dev)
            tp = min(v, entry * (1 + 0.005))  # VWAP 또는 0.5%
        else:
            sl = entry * (1 + sl_dev)
            tp = max(v, entry * (1 - 0.005))

        fb = future_bars(df, i, 12)
        if not fb:
            i += 1; continue

        pnl, _ = execute_trade(entry, direction, sl, tp, fb)
        pnls.append(pnl)
        i += 1

    return eval_results(pnls, [])


# ─── 전략 A5: 변동성 스퀴즈 폭발 ─────────────────────────────────────────────
def strategy_a5(df: pd.DataFrame) -> dict:
    atr          = calc_atr(df)
    _, _, _, bw  = calc_bb(df, 20)
    atr_ma10     = atr.rolling(10).mean()
    pnls         = []
    warmup       = 30
    in_squeeze   = False

    i = warmup
    while i < len(df) - 1:
        a   = atr.iloc[i]
        bwi = bw.iloc[i]
        am10 = atr_ma10.iloc[i]
        if pd.isna(a) or pd.isna(bwi) or pd.isna(am10) or am10 == 0:
            i += 1; continue

        bw_min20 = bw.iloc[max(0, i-20):i].min()
        is_squeeze = (bwi <= bw_min20 * 1.001) and (a <= am10 * 0.5)

        if is_squeeze:
            in_squeeze = True
            i += 1; continue

        if in_squeeze:
            in_squeeze = False
            # 직전 봉들의 고점/저점
            prev_high = df["high"].iloc[max(0, i-5):i].max()
            prev_low  = df["low"].iloc[max(0, i-5):i].min()
            cur_close = df["close"].iloc[i]

            if cur_close > prev_high:
                direction = 1
            elif cur_close < prev_low:
                direction = -1
            else:
                i += 1; continue

            entry = cur_close
            sl    = entry - direction * a * 0.8
            tp    = entry + direction * a * 3.0

            fb = future_bars(df, i, 20)
            if not fb:
                i += 1; continue

            pnl, _ = execute_trade(entry, direction, sl, tp, fb)
            pnls.append(pnl)

        i += 1

    return eval_results(pnls, [])


# ─── 전략 A6: 고거래량 역추세 ─────────────────────────────────────────────────
def strategy_a6(df: pd.DataFrame) -> dict:
    atr    = calc_atr(df)
    rsi    = calc_rsi(df)
    vol_ma = df["volume"].rolling(20).mean()
    pnls   = []
    warmup = 25

    i = warmup
    while i < len(df) - 1:
        a   = atr.iloc[i]
        vma = vol_ma.iloc[i]
        r   = rsi.iloc[i]
        if pd.isna(a) or pd.isna(vma) or pd.isna(r) or a == 0 or vma == 0:
            i += 1; continue

        vol_cur     = df["volume"].iloc[i]
        candle_size = df["high"].iloc[i] - df["low"].iloc[i]

        if vol_cur < vma * 3.0:
            i += 1; continue
        if candle_size < a * 1.5:
            i += 1; continue

        # RSI 과매수/과매도
        if r > 70:
            direction = -1  # short
        elif r < 30:
            direction = 1   # long
        else:
            i += 1; continue

        entry = df["close"].iloc[i]
        sl    = entry - direction * a * 1.2
        tp    = entry + direction * a * 2.0

        fb = future_bars(df, i, 15)
        if not fb:
            i += 1; continue

        pnl, _ = execute_trade(entry, direction, sl, tp, fb)
        pnls.append(pnl)
        i += 1

    return eval_results(pnls, [])


# ─── 전략 A7: 크로스 심볼 모멘텀 전이 ────────────────────────────────────────
def strategy_a7(btc: pd.DataFrame, alt: pd.DataFrame, alt_name: str) -> dict:
    btc_atr = calc_atr(btc)
    alt_atr = calc_atr(alt)
    pnls    = []
    warmup  = 20

    # 시간 인덱스 정렬
    common  = btc.index.intersection(alt.index)
    btc_c   = btc.reindex(common)
    alt_c   = alt.reindex(common)
    ba_c    = btc_atr.reindex(common)
    aa_c    = alt_atr.reindex(common)

    i = warmup
    while i < len(common) - 2:
        b_atr = ba_c.iloc[i]
        a_atr = aa_c.iloc[i]
        if pd.isna(b_atr) or pd.isna(a_atr) or b_atr == 0:
            i += 1; continue

        btc_body = btc_c["close"].iloc[i] - btc_c["open"].iloc[i]

        # BTC ATR×2 이상 강한 상승
        if btc_body < b_atr * 2.0:
            i += 1; continue

        # 1봉 지연 후 ALT 진입
        next_i = i + 1
        if next_i >= len(common):
            i += 1; continue

        entry  = alt_c["close"].iloc[next_i]
        a_atr2 = aa_c.iloc[next_i]
        if pd.isna(a_atr2) or a_atr2 == 0:
            i += 1; continue

        sl    = entry - a_atr2 * 0.8
        # 최대 3봉 보유 (TP 없음 → TIMEOUT)
        tp    = entry + a_atr2 * 99   # 사실상 TP 없음, 시간 청산
        fb    = future_bars(alt_c, next_i, 3)
        if not fb:
            i += 1; continue

        pnl, _ = execute_trade(entry, 1, sl, tp, fb)
        pnls.append(pnl)
        i += 1

    return eval_results(pnls, [])


# ─── 메인 ─────────────────────────────────────────────────────────────────────
def qualify(res: dict) -> bool:
    if res["trades"] < MIN_TRADES:
        return False
    pf_ok = res["pf"] >= MIN_PF
    wr_ok = res["wr"] >= MIN_WR
    rr_ok = res["avg_rr"] >= MIN_RR
    return pf_ok and (wr_ok or rr_ok)


def main():
    print("=" * 65)
    print(" 소자본 한탕 전략 백테스트  A1~A7")
    print(f" 수수료 {FEE_RT*100:.2f}% + 슬리피지 {SLIP_RT*100:.2f}% 왕복")
    print(f" 기간 {DAYS}일 | 1h 캔들 | {', '.join(SYMBOLS)}")
    print("=" * 65)

    # 데이터 로드
    print("\n[1] 데이터 로드")
    data = {}
    for sym in SYMBOLS:
        print(f"  {sym}...", end=" ")
        df = get_ohlcv(sym)
        if df is None or df.empty or len(df) < 50:
            print(f"  !! {sym} 데이터 불충분, 스킵")
            continue
        data[sym] = df

    if not data:
        print("데이터 없음. 종료.")
        return

    # 전략 실행
    print("\n[2] 전략 실행")
    all_results = []

    for sym, df in data.items():
        print(f"\n  ── {sym} ──")

        r = strategy_a1(df)
        all_results.append({"strategy": "A1 연속3봉반전", "symbol": sym, **r})
        print(f"  A1: {r['trades']}건 PF={r['pf']} WR={r['wr']:.1%}")

        r = strategy_a2(df)
        all_results.append({"strategy": "A2 이중바닥/천장", "symbol": sym, **r})
        print(f"  A2: {r['trades']}건 PF={r['pf']} WR={r['wr']:.1%}")

        r = strategy_a3(df)
        all_results.append({"strategy": "A3 빅캔들추종", "symbol": sym, **r})
        print(f"  A3: {r['trades']}건 PF={r['pf']} WR={r['wr']:.1%}")

        r = strategy_a4(df)
        all_results.append({"strategy": "A4 VWAP평균회귀", "symbol": sym, **r})
        print(f"  A4: {r['trades']}건 PF={r['pf']} WR={r['wr']:.1%}")

        r = strategy_a5(df)
        all_results.append({"strategy": "A5 변동성스퀴즈", "symbol": sym, **r})
        print(f"  A5: {r['trades']}건 PF={r['pf']} WR={r['wr']:.1%}")

        r = strategy_a6(df)
        all_results.append({"strategy": "A6 고거래량역추세", "symbol": sym, **r})
        print(f"  A6: {r['trades']}건 PF={r['pf']} WR={r['wr']:.1%}")

    # A7: 크로스 심볼 (BTC + ALT)
    print(f"\n  ── A7 크로스심볼 ──")
    if "BTCUSDT" in data:
        for alt_sym in ["SOLUSDT", "XRPUSDT", "ETHUSDT"]:
            if alt_sym in data:
                r = strategy_a7(data["BTCUSDT"], data[alt_sym], alt_sym)
                all_results.append({"strategy": "A7 BTC→ALT지연", "symbol": alt_sym, **r})
                print(f"  A7/{alt_sym}: {r['trades']}건 PF={r['pf']} WR={r['wr']:.1%}")

    # 결과 정렬 및 출력
    print("\n" + "=" * 65)
    print(" 결과 요약 (PF 내림차순)")
    print("=" * 65)

    sorted_res = sorted(all_results, key=lambda x: x["pf"], reverse=True)

    fmt = "{:<3} {:<18} {:<8} {:>5} {:>6} {:>6} {:>7} {:>8}"
    print(fmt.format("순위","전략","심볼","거래","PF","승률","R:R","누적P&L%"))
    print("-" * 65)

    candidates = []
    for rank, r in enumerate(sorted_res, 1):
        star = ""
        if qualify(r):
            star = " ⭐편입후보"
            candidates.append(r)
        trades_ok = "✓" if r["trades"] >= MIN_TRADES else "✗"
        pf_ok     = "✓" if r["pf"] >= MIN_PF else "✗"
        wr_ok     = "✓" if r["wr"] >= MIN_WR else "~"
        rr_ok     = "✓" if r["avg_rr"] >= MIN_RR else "~"

        print(f"#{rank:<3} {r['strategy']:<18} {r['symbol']:<8} "
              f"{r['trades']:>4}건{trades_ok} "
              f"PF{r['pf']:>4}{pf_ok} "
              f"WR{r['wr']:.0%}{wr_ok} "
              f"RR{r['avg_rr']:.2f}{rr_ok} "
              f"{r['total_pnl']:>+7.1f}%"
              f"{star}")

    print("=" * 65)
    print(f"\n⭐ 편입 후보 ({len(candidates)}건, PF≥{MIN_PF} & 거래≥{MIN_TRADES} & WR≥{MIN_WR:.0%} or RR≥{MIN_RR})")
    if candidates:
        for c in sorted(candidates, key=lambda x: x["pf"], reverse=True):
            print(f"  → {c['strategy']} / {c['symbol']}: "
                  f"PF={c['pf']} | 거래={c['trades']}건 | "
                  f"WR={c['wr']:.1%} | RR={c['avg_rr']:.2f} | "
                  f"누적={c['total_pnl']:+.1f}%")
    else:
        print("  (기준 통과 전략 없음)")

    print("\n[완료]")


if __name__ == "__main__":
    main()
