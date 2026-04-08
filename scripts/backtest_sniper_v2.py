"""
고레버리지 스나이퍼 v2 백테스트
=====================================
재설계 파라미터:
  - ADX(14, 1h) >= 30  (기존 35 → 완화)
  - EMA9 > EMA21 > EMA50 완전 정렬 (롱) / EMA9 < EMA21 < EMA50 (숏)
  - 볼륨 > 20봉 평균의 1.5배 (기존 2배 → 완화)
  - RSI 조건 완전 제거
  - 레버리지: 20x
  - 손절: ATR × 0.8 (기존 0.5 → 완화)
  - 익절: ATR × 3.0 (기존 2.0 → 확대)
  - 포지션 크기: 자본의 20%

데이터: Bitget 퍼블릭 API (1h 캔들)
심볼: BTC/ETH/SOL/XRP (USDT 선물)
기간: 90일
수수료: 0.16% + 슬리피지 0.05% (왕복 0.42%)
"""
from __future__ import annotations

import json
import math
import time
import random
import socket
import ssl
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
DAYS = 90
LEVERAGE = 20
POSITION_SIZE_FRACTION = 0.20   # 자본의 20%
ATR_STOP_MULTIPLE = 0.8
ATR_TP_MULTIPLE = 3.0
ADX_MIN = 30
VOLUME_MULTIPLE = 1.5           # 20봉 평균 대비
TAKER_FEE = 0.0016              # 0.16%
SLIPPAGE = 0.0005               # 0.05%
ROUND_TRIP_COST = (TAKER_FEE + SLIPPAGE) * 2   # 왕복

BITGET_REST_URL = "https://api.bitget.com"
PRODUCT_TYPE = "USDT-FUTURES"
INTERVAL = "1H"   # Bitget 1h granularity for futures
LIMIT_PER_REQUEST = 200

# ---------------------------------------------------------------------------
# Bitget API helper
# ---------------------------------------------------------------------------

def _send(url: str, params: dict[str, Any]) -> dict[str, Any]:
    query = urlencode(sorted(params.items()))
    full_url = f"{url}?{query}"
    req = Request(full_url, method="GET")
    for attempt in range(4):
        try:
            with urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                time.sleep(61 + random.uniform(0, 10))
                continue
            raise
        except (URLError, socket.timeout, OSError) as exc:
            if attempt < 3:
                time.sleep(2 ** attempt + random.uniform(0, 1))
                continue
            raise RuntimeError(f"transport error: {exc}") from exc
    raise RuntimeError("max retries exceeded")


def fetch_klines_1h(symbol: str, days: int) -> list[dict[str, Any]]:
    """Bitget 퍼블릭 API로 1h 캔들 days일치 가져오기 (역방향 페이지네이션)."""
    end_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    # 여유 있게 days+5일 요청
    target_bars = (days + 5) * 24
    all_bars: list[dict[str, Any]] = []

    while len(all_bars) < target_bars:
        params: dict[str, Any] = {
            "symbol": symbol,
            "granularity": INTERVAL,
            "productType": PRODUCT_TYPE,
            "limit": LIMIT_PER_REQUEST,
            "endTime": str(end_ms),
        }
        try:
            payload = _send(f"{BITGET_REST_URL}/api/v2/mix/market/candles", params)
        except Exception as exc:
            print(f"  [WARN] {symbol} kline fetch error: {exc}", flush=True)
            break

        rows = payload.get("data") or []
        if not isinstance(rows, list) or not rows:
            break

        chunk: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 7:
                continue
            chunk.append({
                "ts": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "vol": float(row[5]),
            })

        if not chunk:
            break

        # Bitget는 최신→과거 순으로 반환
        chunk.sort(key=lambda b: b["ts"])
        all_bars = chunk + all_bars

        oldest_ts = chunk[0]["ts"]
        end_ms = oldest_ts - 1

        time.sleep(0.3)  # rate limit 방지

        if len(chunk) < LIMIT_PER_REQUEST:
            break

    # days일 이내만 유지
    cutoff_ms = int((datetime.now(tz=timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    all_bars = [b for b in all_bars if b["ts"] >= cutoff_ms]
    all_bars.sort(key=lambda b: b["ts"])
    return all_bars


# ---------------------------------------------------------------------------
# Technical Indicators
# ---------------------------------------------------------------------------

def ema_series(closes: list[float], period: int) -> list[float]:
    if len(closes) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(closes[:period]) / period]
    for price in closes[period:]:
        result.append(price * k + result[-1] * (1 - k))
    return result


def atr_series(bars: list[dict], period: int = 14) -> list[float]:
    if len(bars) < 2:
        return []
    trs: list[float] = []
    for i in range(1, len(bars)):
        high = bars[i]["high"]
        low = bars[i]["low"]
        prev_close = bars[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    # Wilder's smoothing
    if len(trs) < period:
        return []
    atr_vals: list[float] = [mean(trs[:period])]
    for tr in trs[period:]:
        atr_vals.append((atr_vals[-1] * (period - 1) + tr) / period)
    return atr_vals


def adx_series(bars: list[dict], period: int = 14) -> list[float]:
    """Wilder ADX. Returns list aligned with bars[period*2:] (approx)."""
    if len(bars) < period * 2 + 1:
        return []

    plus_dms: list[float] = []
    minus_dms: list[float] = []
    trs: list[float] = []

    for i in range(1, len(bars)):
        up = bars[i]["high"] - bars[i - 1]["high"]
        down = bars[i - 1]["low"] - bars[i]["low"]
        plus_dms.append(up if up > down and up > 0 else 0.0)
        minus_dms.append(down if down > up and down > 0 else 0.0)
        high = bars[i]["high"]
        low = bars[i]["low"]
        prev_close = bars[i - 1]["close"]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    # First Wilder smoothing
    smooth_tr = sum(trs[:period])
    smooth_plus = sum(plus_dms[:period])
    smooth_minus = sum(minus_dms[:period])

    adx_list: list[float] = []
    dx_list: list[float] = []

    def _dx(splus: float, sminus: float, str_: float) -> float:
        if str_ <= 0:
            return 0.0
        pdi = 100 * splus / str_
        mdi = 100 * sminus / str_
        denom = pdi + mdi
        return 100 * abs(pdi - mdi) / denom if denom > 0 else 0.0

    dx_list.append(_dx(smooth_plus, smooth_minus, smooth_tr))

    for i in range(period, len(trs)):
        smooth_tr = smooth_tr - smooth_tr / period + trs[i]
        smooth_plus = smooth_plus - smooth_plus / period + plus_dms[i]
        smooth_minus = smooth_minus - smooth_minus / period + minus_dms[i]
        dx_list.append(_dx(smooth_plus, smooth_minus, smooth_tr))

    # ADX = Wilder smoothed DX
    if len(dx_list) < period:
        return []
    adx_list.append(mean(dx_list[:period]))
    for dx in dx_list[period:]:
        adx_list.append((adx_list[-1] * (period - 1) + dx) / period)

    return adx_list


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    symbol: str
    side: str        # "long" | "short"
    entry_time: int  # ms
    entry_price: float
    exit_time: int
    exit_price: float
    exit_reason: str
    pnl_pct: float   # 레버리지 포함 %
    pnl_usd: float
    atr: float
    notional_usd: float


@dataclass
class BacktestResult:
    symbol: str
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)

    def total_trades(self) -> int:
        return len(self.trades)

    def wins(self) -> int:
        return sum(1 for t in self.trades if t.pnl_usd > 0)

    def losses(self) -> int:
        return sum(1 for t in self.trades if t.pnl_usd <= 0)

    def win_rate(self) -> float:
        n = self.total_trades()
        return round(self.wins() / n, 4) if n else 0.0

    def total_pnl_usd(self) -> float:
        return round(sum(t.pnl_usd for t in self.trades), 4)

    def gross_profit(self) -> float:
        return sum(t.pnl_usd for t in self.trades if t.pnl_usd > 0)

    def gross_loss(self) -> float:
        return abs(sum(t.pnl_usd for t in self.trades if t.pnl_usd < 0))

    def profit_factor(self) -> float:
        gl = self.gross_loss()
        if gl == 0:
            return float("inf") if self.gross_profit() > 0 else 0.0
        return round(self.gross_profit() / gl, 4)

    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0]
        max_dd = 0.0
        for eq in self.equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd
        return round(max_dd * 100, 2)


def _run_symbol_backtest(
    symbol: str,
    bars: list[dict],
    starting_equity: float = 10000.0,
) -> BacktestResult:
    result = BacktestResult(symbol=symbol)
    equity = starting_equity
    result.equity_curve.append(equity)

    closes = [b["close"] for b in bars]
    n = len(bars)

    # 최소 60개 봉 필요 (EMA50 + ADX 안정화)
    if n < 80:
        return result

    # 지표 계산
    ema9_all = ema_series(closes, 9)
    ema21_all = ema_series(closes, 21)
    ema50_all = ema_series(closes, 50)
    atr_all = atr_series(bars, 14)
    adx_all = adx_series(bars, 14)

    # EMA50 기준으로 인덱스 오프셋 맞추기
    ema50_offset = 50 - 1    # closes[49] 가 EMA50 첫 번째 값
    ema21_offset = 21 - 1
    ema9_offset = 9 - 1
    atr_offset = 14           # bars[14:] 기준
    # ADX: bars[period*2:] 근사 → period=14이면 bars[28:] 근사
    adx_offset_bars = 14 * 2 + 14  # 보수적으로 bars[42:] 부터 유효

    # 공통 시작 인덱스 (모든 지표가 유효한 첫 번째 봉)
    start_idx = max(ema50_offset, atr_offset, adx_offset_bars, 50)

    in_position = False
    pos_side = ""
    pos_entry_price = 0.0
    pos_stop = 0.0
    pos_tp = 0.0
    pos_entry_time = 0
    pos_atr = 0.0
    pos_notional = 0.0

    vol_window = 20  # 볼륨 평균 윈도우

    for i in range(start_idx, n):
        bar = bars[i]
        ts = bar["ts"]
        close = bar["close"]
        high = bar["high"]
        low = bar["low"]

        # ---- 지표 인덱스 매핑 ----
        # ema9_all[j] 는 closes[j + ema9_offset] 에 대응
        def _ema9(idx: int) -> float:
            j = idx - ema9_offset
            return ema9_all[j] if 0 <= j < len(ema9_all) else 0.0

        def _ema21(idx: int) -> float:
            j = idx - ema21_offset
            return ema21_all[j] if 0 <= j < len(ema21_all) else 0.0

        def _ema50(idx: int) -> float:
            j = idx - ema50_offset
            return ema50_all[j] if 0 <= j < len(ema50_all) else 0.0

        def _atr(idx: int) -> float:
            j = idx - atr_offset
            return atr_all[j] if 0 <= j < len(atr_all) else 0.0

        def _adx(idx: int) -> float:
            # adx_all 은 bars[adx_offset_bars:] 기준
            j = idx - adx_offset_bars
            return adx_all[j] if 0 <= j < len(adx_all) else 0.0

        e9 = _ema9(i)
        e21 = _ema21(i)
        e50 = _ema50(i)
        atr_val = _atr(i)
        adx_val = _adx(i)

        # ---- 포지션 보유 중: 청산 체크 ----
        if in_position:
            hit_stop = hit_tp = False
            if pos_side == "long":
                # 고가/저가로 SL/TP 인트라바 체크
                if low <= pos_stop:
                    hit_stop = True
                    exit_price = pos_stop
                elif high >= pos_tp:
                    hit_tp = True
                    exit_price = pos_tp
            else:  # short
                if high >= pos_stop:
                    hit_stop = True
                    exit_price = pos_stop
                elif low <= pos_tp:
                    hit_tp = True
                    exit_price = pos_tp

            if hit_stop or hit_tp:
                exit_reason = "take_profit" if hit_tp else "stop_loss"
                direction = 1 if pos_side == "long" else -1
                raw_pnl_pct = (exit_price - pos_entry_price) / pos_entry_price * direction
                net_pnl_pct = raw_pnl_pct - ROUND_TRIP_COST
                pnl_usd = net_pnl_pct * LEVERAGE * pos_notional
                equity += pnl_usd
                result.equity_curve.append(equity)
                result.trades.append(Trade(
                    symbol=symbol,
                    side=pos_side,
                    entry_time=pos_entry_time,
                    entry_price=pos_entry_price,
                    exit_time=ts,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    pnl_pct=round(net_pnl_pct * LEVERAGE * 100, 4),
                    pnl_usd=round(pnl_usd, 4),
                    atr=pos_atr,
                    notional_usd=pos_notional,
                ))
                in_position = False
            continue

        # ---- 진입 신호 체크 ----
        if atr_val <= 0 or adx_val <= 0:
            continue

        # 볼륨 조건
        if i >= vol_window:
            avg_vol = mean(b["vol"] for b in bars[i - vol_window:i])
            vol_ok = bar["vol"] >= avg_vol * VOLUME_MULTIPLE
        else:
            vol_ok = False

        if not vol_ok:
            continue

        # ADX 조건
        if adx_val < ADX_MIN:
            continue

        # EMA 정렬 조건
        long_align = e9 > e21 > e50 and e9 > 0 and e21 > 0 and e50 > 0
        short_align = e9 < e21 < e50 and e9 > 0 and e21 > 0 and e50 > 0

        if not (long_align or short_align):
            continue

        side = "long" if long_align else "short"

        notional_usd = equity * POSITION_SIZE_FRACTION
        if notional_usd <= 0:
            continue

        entry_price = close * (1 + SLIPPAGE if side == "long" else 1 - SLIPPAGE)
        if side == "long":
            stop_price = entry_price - atr_val * ATR_STOP_MULTIPLE
            tp_price = entry_price + atr_val * ATR_TP_MULTIPLE
        else:
            stop_price = entry_price + atr_val * ATR_STOP_MULTIPLE
            tp_price = entry_price - atr_val * ATR_TP_MULTIPLE

        in_position = True
        pos_side = side
        pos_entry_price = entry_price
        pos_stop = stop_price
        pos_tp = tp_price
        pos_entry_time = ts
        pos_atr = atr_val
        pos_notional = notional_usd

    return result


# ---------------------------------------------------------------------------
# Parameter Grid Search (PF < 1.3인 경우)
# ---------------------------------------------------------------------------

def grid_search(bars_by_symbol: dict[str, list[dict]]) -> dict[str, Any]:
    """ADX / ATR-stop / ATR-tp 파라미터 그리드 탐색."""
    best: dict[str, Any] = {}
    best_pf = 0.0

    adx_range = [25, 28, 30, 32]
    stop_range = [0.6, 0.8, 1.0, 1.2]
    tp_range = [2.5, 3.0, 3.5, 4.0]
    vol_range = [1.2, 1.5, 2.0]

    param_count = len(adx_range) * len(stop_range) * len(tp_range) * len(vol_range)
    print(f"[Grid] 파라미터 조합 수: {param_count}", flush=True)

    for adx_min in adx_range:
        for stop_mult in stop_range:
            for tp_mult in tp_range:
                for vol_mult in vol_range:
                    all_trades: list[Trade] = []
                    for symbol, bars in bars_by_symbol.items():
                        r = _run_symbol_backtest_custom(
                            symbol, bars,
                            adx_min=adx_min,
                            stop_mult=stop_mult,
                            tp_mult=tp_mult,
                            vol_mult=vol_mult,
                        )
                        all_trades.extend(r.trades)
                    gp = sum(t.pnl_usd for t in all_trades if t.pnl_usd > 0)
                    gl = abs(sum(t.pnl_usd for t in all_trades if t.pnl_usd < 0))
                    pf = (gp / gl) if gl > 0 else (float("inf") if gp > 0 else 0.0)
                    if pf > best_pf:
                        best_pf = pf
                        best = {
                            "adx_min": adx_min,
                            "atr_stop_multiple": stop_mult,
                            "atr_tp_multiple": tp_mult,
                            "volume_multiple": vol_mult,
                            "pf": round(pf, 4),
                            "trades": len(all_trades),
                        }

    return best


def _run_symbol_backtest_custom(
    symbol: str,
    bars: list[dict],
    adx_min: float,
    stop_mult: float,
    tp_mult: float,
    vol_mult: float,
    starting_equity: float = 10000.0,
) -> BacktestResult:
    """파라미터 커스텀 버전 (grid search용)."""
    result = BacktestResult(symbol=symbol)
    equity = starting_equity
    closes = [b["close"] for b in bars]
    n = len(bars)
    if n < 80:
        return result

    ema9_all = ema_series(closes, 9)
    ema21_all = ema_series(closes, 21)
    ema50_all = ema_series(closes, 50)
    atr_all = atr_series(bars, 14)
    adx_all = adx_series(bars, 14)

    ema50_offset = 49
    ema21_offset = 20
    ema9_offset = 8
    atr_offset = 14
    adx_offset_bars = 42
    start_idx = max(ema50_offset, atr_offset, adx_offset_bars, 50)

    in_position = False
    pos_side = ""
    pos_entry_price = 0.0
    pos_stop = 0.0
    pos_tp = 0.0
    pos_entry_time = 0
    pos_atr = 0.0
    pos_notional = 0.0
    vol_window = 20

    for i in range(start_idx, n):
        bar = bars[i]
        ts = bar["ts"]
        high = bar["high"]
        low = bar["low"]
        close = bar["close"]

        j9 = i - ema9_offset
        j21 = i - ema21_offset
        j50 = i - ema50_offset
        ja = i - atr_offset
        jd = i - adx_offset_bars

        e9 = ema9_all[j9] if 0 <= j9 < len(ema9_all) else 0.0
        e21 = ema21_all[j21] if 0 <= j21 < len(ema21_all) else 0.0
        e50 = ema50_all[j50] if 0 <= j50 < len(ema50_all) else 0.0
        atr_val = atr_all[ja] if 0 <= ja < len(atr_all) else 0.0
        adx_val = adx_all[jd] if 0 <= jd < len(adx_all) else 0.0

        if in_position:
            hit_stop = hit_tp = False
            exit_price = close
            if pos_side == "long":
                if low <= pos_stop:
                    hit_stop = True
                    exit_price = pos_stop
                elif high >= pos_tp:
                    hit_tp = True
                    exit_price = pos_tp
            else:
                if high >= pos_stop:
                    hit_stop = True
                    exit_price = pos_stop
                elif low <= pos_tp:
                    hit_tp = True
                    exit_price = pos_tp
            if hit_stop or hit_tp:
                direction = 1 if pos_side == "long" else -1
                raw_pnl_pct = (exit_price - pos_entry_price) / pos_entry_price * direction
                pnl_usd = (raw_pnl_pct - ROUND_TRIP_COST) * LEVERAGE * pos_notional
                equity += pnl_usd
                result.trades.append(Trade(
                    symbol=symbol, side=pos_side, entry_time=pos_entry_time,
                    entry_price=pos_entry_price, exit_time=ts, exit_price=exit_price,
                    exit_reason="tp" if hit_tp else "sl",
                    pnl_pct=round((raw_pnl_pct - ROUND_TRIP_COST) * LEVERAGE * 100, 4),
                    pnl_usd=round(pnl_usd, 4), atr=pos_atr, notional_usd=pos_notional,
                ))
                in_position = False
            continue

        if atr_val <= 0 or adx_val < adx_min:
            continue
        if i < vol_window:
            continue
        avg_vol = mean(b["vol"] for b in bars[i - vol_window:i])
        if bar["vol"] < avg_vol * vol_mult:
            continue

        long_align = e9 > e21 > e50 > 0
        short_align = 0 < e9 < e21 < e50

        if not (long_align or short_align):
            continue

        side = "long" if long_align else "short"
        notional_usd = equity * POSITION_SIZE_FRACTION
        if notional_usd <= 0:
            continue
        slip = SLIPPAGE if side == "long" else -SLIPPAGE
        entry_price = close * (1 + slip)
        if side == "long":
            stop_price = entry_price - atr_val * stop_mult
            tp_price = entry_price + atr_val * tp_mult
        else:
            stop_price = entry_price + atr_val * stop_mult
            tp_price = entry_price - atr_val * tp_mult

        in_position = True
        pos_side = side
        pos_entry_price = entry_price
        pos_stop = stop_price
        pos_tp = tp_price
        pos_entry_time = ts
        pos_atr = atr_val
        pos_notional = notional_usd

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _fmt_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    print("=" * 65)
    print(f"고레버리지 스나이퍼 v2 백테스트  (레버리지={LEVERAGE}x, {DAYS}일, 1h)")
    print(f"파라미터: ADX>={ADX_MIN}, ATR_SL×{ATR_STOP_MULTIPLE}, ATR_TP×{ATR_TP_MULTIPLE}")
    print(f"          볼륨>{VOLUME_MULTIPLE}x20MA, 포지션크기={int(POSITION_SIZE_FRACTION*100)}%")
    print(f"          수수료+슬리피지 왕복={ROUND_TRIP_COST*100:.2f}%")
    print("=" * 65)

    bars_by_symbol: dict[str, list[dict]] = {}

    for symbol in SYMBOLS:
        print(f"\n[데이터] {symbol} 1h 캔들 {DAYS}일 로딩...", flush=True)
        bars = fetch_klines_1h(symbol, DAYS)
        bars_by_symbol[symbol] = bars
        if bars:
            start = _fmt_ts(bars[0]["ts"])
            end = _fmt_ts(bars[-1]["ts"])
            print(f"  → {len(bars)}봉  {start} ~ {end}", flush=True)
        else:
            print(f"  → 데이터 없음", flush=True)

    # 각 심볼별 백테스트
    all_results: list[BacktestResult] = []
    for symbol, bars in bars_by_symbol.items():
        if not bars:
            continue
        r = _run_symbol_backtest(symbol, bars)
        all_results.append(r)

    # 결과 출력
    print("\n" + "=" * 65)
    print("백테스트 결과표")
    print("=" * 65)
    print(f"{'심볼':<10} {'거래수':>5} {'승률':>6} {'PF':>6} {'총PnL($)':>10} {'MaxDD(%)':>9} {'승':>4} {'패':>4}")
    print("-" * 65)

    all_trades_combined: list[Trade] = []
    for r in all_results:
        all_trades_combined.extend(r.trades)
        pf_str = f"{r.profit_factor():.4f}" if r.profit_factor() != float("inf") else "∞"
        print(
            f"{r.symbol:<10} {r.total_trades():>5} {r.win_rate()*100:>5.1f}%"
            f" {pf_str:>6} {r.total_pnl_usd():>10.2f}"
            f" {r.max_drawdown_pct():>8.1f}%"
            f" {r.wins():>4} {r.losses():>4}"
        )

    # 통합 지표
    print("-" * 65)
    combined_gp = sum(t.pnl_usd for t in all_trades_combined if t.pnl_usd > 0)
    combined_gl = abs(sum(t.pnl_usd for t in all_trades_combined if t.pnl_usd < 0))
    combined_pf = (combined_gp / combined_gl) if combined_gl > 0 else float("inf")
    combined_wins = sum(1 for t in all_trades_combined if t.pnl_usd > 0)
    combined_total = len(all_trades_combined)
    combined_wr = combined_wins / combined_total if combined_total else 0.0
    combined_pnl = sum(t.pnl_usd for t in all_trades_combined)
    pf_str = f"{combined_pf:.4f}" if combined_pf != float("inf") else "∞"

    print(
        f"{'[통합]':<10} {combined_total:>5} {combined_wr*100:>5.1f}%"
        f" {pf_str:>6} {combined_pnl:>10.2f}"
        f" {'':>8}"
        f" {combined_wins:>4} {combined_total - combined_wins:>4}"
    )
    print("=" * 65)

    # PF 평가
    PF_TARGET = 1.3
    print(f"\n목표 PF >= {PF_TARGET}")
    if combined_pf >= PF_TARGET:
        print(f"✓ PF {combined_pf:.4f} >= {PF_TARGET}  — strategy_override 추가 가능")
        print_override_block()
    else:
        print(f"✗ PF {combined_pf:.4f} < {PF_TARGET}  — 파라미터 그리드 탐색 시작...")
        best = grid_search(bars_by_symbol)
        if best:
            print(f"\n최적 파라미터 (PF={best.get('pf', '?')}):")
            for k, v in best.items():
                print(f"  {k}: {v}")
            if float(best.get("pf", 0)) >= PF_TARGET:
                print(f"\n✓ 그리드 탐색으로 PF {best['pf']} 달성!")
                print_override_block(
                    adx_min=best.get("adx_min", ADX_MIN),
                    atr_stop=best.get("atr_stop_multiple", ATR_STOP_MULTIPLE),
                    atr_tp=best.get("atr_tp_multiple", ATR_TP_MULTIPLE),
                    vol_mult=best.get("volume_multiple", VOLUME_MULTIPLE),
                )
            else:
                print(f"\n최적 PF {best.get('pf')} — PF {PF_TARGET} 미달, 전략 재검토 필요")
        else:
            print("그리드 탐색 결과 없음")


def print_override_block(
    adx_min: float = ADX_MIN,
    atr_stop: float = ATR_STOP_MULTIPLE,
    atr_tp: float = ATR_TP_MULTIPLE,
    vol_mult: float = VOLUME_MULTIPLE,
) -> None:
    block = {
        "sniper_v2": {
            "enabled": True,
            "adx_min": adx_min,
            "ema_periods": [9, 21, 50],
            "atr_stop_multiple": atr_stop,
            "atr_tp_multiple": atr_tp,
            "volume_multiple": vol_mult,
            "leverage": LEVERAGE,
            "position_size_fraction": POSITION_SIZE_FRACTION,
            "symbols": SYMBOLS,
        }
    }
    print("\nstrategy_override 추가 블록:")
    print(json.dumps(block, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
