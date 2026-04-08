"""
펀딩비 역추세 전략 레버리지 시나리오 백테스트
레버리지 5x / 10x / 15x 비교 → 최적 레버리지 선택 후 전략 파일에 반영

사용법:
    python scripts/backtest_funding_leverage.py
"""

from __future__ import annotations

import json
import math
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
LOOKBACK_DAYS = 90
FUNDING_THRESHOLD = 0.00015        # 0.015 %
TAKER_FEE_RATE = 0.0006            # 0.06 %
SLIPPAGE_RATE = 0.0005             # 0.05 %
ROUND_TRIP_COST = (TAKER_FEE_R := TAKER_FEE_RATE) * 2 + SLIPPAGE_RATE  # 0.17 %
MAX_HOLD_HOURS = 8
ATR_PERIOD = 14                    # 1h ATR 기간
CAPITAL_USD = 70.0                 # 기준 자본 (월 수익 계산용)
MARGIN_BUFFER = 0.9                # 청산가 마진 버퍼 (10 % 여유)

LEVERAGE_CONFIGS = {
    5:  {"sl_atr": 1.5, "tp_atr": 3.0},
    10: {"sl_atr": 1.0, "tp_atr": 2.5},
    15: {"sl_atr": 0.6, "tp_atr": 2.0},
}

REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORICAL_ROOT = REPO_ROOT / "quant_runtime" / "historical"
OVERRIDE_PATH = REPO_ROOT / "quant_runtime" / "artifacts" / "strategy_override.approved.json"
STRATEGY_FILE = REPO_ROOT / "quant_binance" / "funding_rate_strategy.py"


# ──────────────────────────────────────────────
# 데이터 구조
# ──────────────────────────────────────────────
@dataclass
class Candle:
    ts: int        # ms
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class FundingEntry:
    ts: int        # ms
    rate: float


@dataclass
class Trade:
    symbol: str
    side: Literal["long", "short"]
    leverage: int
    entry_price: float
    exit_price: float
    entry_ts: int
    exit_ts: int
    pnl_pct: float   # 자본 대비 %
    exit_reason: str
    liquidated: bool


# ──────────────────────────────────────────────
# Binance 공개 API 호출
# ──────────────────────────────────────────────
def _fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "quant-backtest/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[Candle]:
    """Binance Futures OHLCV 1h 캔들 (최대 1500개씩 페이지)"""
    candles: list[Candle] = []
    cursor = start_ms
    while cursor < end_ms:
        url = (
            f"https://fapi.binance.com/fapi/v1/klines"
            f"?symbol={symbol}&interval={interval}"
            f"&startTime={cursor}&endTime={end_ms}&limit=1500"
        )
        data = _fetch_json(url)
        if not data:
            break
        for row in data:
            candles.append(Candle(
                ts=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            ))
        cursor = int(data[-1][0]) + 1
        time.sleep(0.12)  # rate-limit
    return candles


def fetch_funding_rates(symbol: str, start_ms: int, end_ms: int) -> list[FundingEntry]:
    """Binance Futures 펀딩비 (8h 주기)"""
    entries: list[FundingEntry] = []
    cursor = start_ms
    while cursor < end_ms:
        url = (
            f"https://fapi.binance.com/fapi/v1/fundingRate"
            f"?symbol={symbol}&startTime={cursor}&endTime={end_ms}&limit=1000"
        )
        data = _fetch_json(url)
        if not data:
            break
        for row in data:
            entries.append(FundingEntry(ts=int(row["fundingTime"]), rate=float(row["fundingRate"])))
        if len(data) < 1000:
            break
        cursor = int(data[-1]["fundingTime"]) + 1
        time.sleep(0.1)
    return entries


# ──────────────────────────────────────────────
# ATR 계산
# ──────────────────────────────────────────────
def compute_atr(candles: list[Candle], period: int = ATR_PERIOD) -> dict[int, float]:
    """ts → ATR 매핑 반환"""
    atr_map: dict[int, float] = {}
    trs: list[float] = []
    for i, c in enumerate(candles):
        if i == 0:
            trs.append(c.high - c.low)
        else:
            prev_close = candles[i - 1].close
            tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
            trs.append(tr)
        if i >= period - 1:
            atr_map[c.ts] = sum(trs[max(0, i - period + 1): i + 1]) / period
    return atr_map


# ──────────────────────────────────────────────
# 단일 심볼 백테스트
# ──────────────────────────────────────────────
def backtest_symbol(
    symbol: str,
    candles: list[Candle],
    funding_rates: list[FundingEntry],
    leverage: int,
    sl_atr_mult: float,
    tp_atr_mult: float,
) -> list[Trade]:
    if not candles or not funding_rates:
        return []

    atr_map = compute_atr(candles, ATR_PERIOD)
    # ts → candle 인덱스 (빠른 탐색)
    candle_by_ts: dict[int, int] = {c.ts: idx for idx, c in enumerate(candles)}

    trades: list[Trade] = []

    for fr in funding_rates:
        if abs(fr.rate) < FUNDING_THRESHOLD:
            continue

        side: Literal["long", "short"] = "short" if fr.rate > 0 else "long"

        # 펀딩비 타임스탬프 직후 1h 캔들 찾기
        entry_idx = None
        for c in candles:
            if c.ts >= fr.ts:
                entry_idx = candle_by_ts.get(c.ts)
                break
        if entry_idx is None or entry_idx not in range(len(candles)):
            continue
        entry_candle = candles[entry_idx]

        atr = atr_map.get(entry_candle.ts)
        if atr is None or atr == 0:
            continue

        entry_price = entry_candle.close * (1 + SLIPPAGE_RATE if side == "long" else 1 - SLIPPAGE_RATE)

        # SL / TP / 청산가 (가격 기준)
        sl_dist = atr * sl_atr_mult
        tp_dist = atr * tp_atr_mult
        liq_dist = entry_price / leverage * MARGIN_BUFFER

        if side == "long":
            sl_price = entry_price - sl_dist
            tp_price = entry_price + tp_dist
            liq_price = entry_price - liq_dist
        else:
            sl_price = entry_price + sl_dist
            tp_price = entry_price - tp_dist
            liq_price = entry_price + liq_dist

        # 후속 캔들 순회 (max_hold 제한)
        exit_price = None
        exit_reason = "max_hold"
        liquidated = False
        last_idx = min(entry_idx + MAX_HOLD_HOURS, len(candles) - 1)

        for i in range(entry_idx + 1, last_idx + 1):
            c = candles[i]
            if side == "long":
                if c.low <= liq_price:
                    exit_price = liq_price
                    exit_reason = "liquidation"
                    liquidated = True
                    break
                if c.low <= sl_price:
                    exit_price = sl_price
                    exit_reason = "stop_loss"
                    break
                if c.high >= tp_price:
                    exit_price = tp_price
                    exit_reason = "take_profit"
                    break
            else:
                if c.high >= liq_price:
                    exit_price = liq_price
                    exit_reason = "liquidation"
                    liquidated = True
                    break
                if c.high >= sl_price:
                    exit_price = sl_price
                    exit_reason = "stop_loss"
                    break
                if c.low <= tp_price:
                    exit_price = tp_price
                    exit_reason = "take_profit"
                    break

        if exit_price is None:
            exit_price = candles[last_idx].close
        exit_ts = candles[min(entry_idx + MAX_HOLD_HOURS, len(candles) - 1)].ts

        # PnL 계산 (자본 대비 %)
        if side == "long":
            price_chg_pct = (exit_price - entry_price) / entry_price
        else:
            price_chg_pct = (entry_price - exit_price) / entry_price

        cost = ROUND_TRIP_COST  # 수수료 + 슬리피지
        pnl_pct = price_chg_pct * leverage - cost * leverage

        if liquidated:
            pnl_pct = -1.0  # 전액 손실

        trades.append(Trade(
            symbol=symbol,
            side=side,
            leverage=leverage,
            entry_price=entry_price,
            exit_price=exit_price,
            entry_ts=entry_candle.ts,
            exit_ts=exit_ts,
            pnl_pct=pnl_pct,
            exit_reason=exit_reason,
            liquidated=liquidated,
        ))

    return trades


# ──────────────────────────────────────────────
# 메트릭 계산
# ──────────────────────────────────────────────
@dataclass
class BacktestResult:
    leverage: int
    total_trades: int
    win_rate: float
    profit_factor: float
    total_return_pct: float
    mdd_pct: float
    max_consec_losses: int
    worst_trade_pct: float
    monthly_return_usd: float
    liquidations: int
    passes: bool


def compute_metrics(trades: list[Trade], leverage: int, capital: float) -> BacktestResult:
    if not trades:
        return BacktestResult(leverage, 0, 0, 0, 0, 0, 0, 0, 0, 0, False)

    total_trades = len(trades)
    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    win_rate = len(wins) / total_trades * 100

    gross_profit = sum(t.pnl_pct for t in wins)
    gross_loss = abs(sum(t.pnl_pct for t in losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # 누적 수익 곡선
    equity = [0.0]
    for t in trades:
        equity.append(equity[-1] + t.pnl_pct)

    total_return_pct = equity[-1] * 100  # %

    # MDD
    peak = -math.inf
    mdd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e)
        if dd > mdd:
            mdd = dd
    mdd_pct = mdd * 100

    # 최대 연속 손실
    max_consec = 0
    cur_consec = 0
    for t in trades:
        if t.pnl_pct <= 0:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0

    worst_trade_pct = min(t.pnl_pct for t in trades) * 100
    liquidations = sum(1 for t in trades if t.liquidated)

    monthly_days = 30
    daily_return = (total_return_pct / 100) / LOOKBACK_DAYS
    monthly_return_usd = daily_return * monthly_days * capital

    passes = (
        profit_factor >= 1.5
        and mdd_pct <= 30.0
        and liquidations == 0
    )

    return BacktestResult(
        leverage=leverage,
        total_trades=total_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        total_return_pct=total_return_pct,
        mdd_pct=mdd_pct,
        max_consec_losses=max_consec,
        worst_trade_pct=worst_trade_pct,
        monthly_return_usd=monthly_return_usd,
        liquidations=liquidations,
        passes=passes,
    )


# ──────────────────────────────────────────────
# 데이터 로드 (히스토리컬 우선, 없으면 API)
# ──────────────────────────────────────────────
def load_data(symbol: str, start_ms: int, end_ms: int) -> tuple[list[Candle], list[FundingEntry]]:
    hist_dir = HISTORICAL_ROOT / symbol.lower()
    candles: list[Candle] | None = None
    funding: list[FundingEntry] | None = None

    # 히스토리컬 캔들
    for fname in ("ohlcv_1h.json", "candles_1h.json", "klines_1h.json"):
        fpath = hist_dir / fname
        if fpath.exists():
            raw = json.loads(fpath.read_text())
            candles = [
                Candle(ts=int(r[0]), open=float(r[1]), high=float(r[2]),
                       low=float(r[3]), close=float(r[4]), volume=float(r[5]))
                for r in raw
                if start_ms <= int(r[0]) <= end_ms
            ]
            break

    # 히스토리컬 펀딩비
    for fname in ("funding_rates.json", "funding.json"):
        fpath = hist_dir / fname
        if fpath.exists():
            raw = json.loads(fpath.read_text())
            if isinstance(raw, list):
                funding = [
                    FundingEntry(ts=int(r.get("fundingTime", r.get("ts", 0))),
                                 rate=float(r.get("fundingRate", r.get("rate", 0))))
                    for r in raw
                    if start_ms <= int(r.get("fundingTime", r.get("ts", 0))) <= end_ms
                ]
            break

    # API fallback
    if candles is None:
        print(f"  [{symbol}] 캔들 API 조회 중...")
        candles = fetch_klines(symbol, "1h", start_ms, end_ms)

    if funding is None:
        print(f"  [{symbol}] 펀딩비 API 조회 중...")
        funding = fetch_funding_rates(symbol, start_ms, end_ms)

    # 시간순 정렬
    candles.sort(key=lambda c: c.ts)
    funding.sort(key=lambda f: f.ts)

    return candles, funding


# ──────────────────────────────────────────────
# 결과 출력
# ──────────────────────────────────────────────
def print_results(results: list[BacktestResult]) -> None:
    print()
    print("레버리지별 백테스트 결과 (90일, BTC/ETH/SOL/XRP):")
    print("┌─────────┬──────┬───────┬────────┬───────────┬───────┬────────┬──────┐")
    print("│ 레버리지 │ 거래수 │  승률  │   PF   │  총수익률  │  MDD  │ 월수익 │청산수│")
    print("├─────────┼──────┼───────┼────────┼───────────┼───────┼────────┼──────┤")
    for r in results:
        pf_str = f"{r.profit_factor:.2f}" if r.profit_factor != float("inf") else "∞"
        ok = "✓" if r.passes else "✗"
        print(
            f"│  {r.leverage:>2}x {ok}  │"
            f" {r.total_trades:>4} │"
            f" {r.win_rate:>5.1f}% │"
            f" {pf_str:>6} │"
            f" {r.total_return_pct:>+9.2f}% │"
            f" {r.mdd_pct:>5.1f}% │"
            f" ${r.monthly_return_usd:>6.2f} │"
            f" {r.liquidations:>4} │"
        )
    print("└─────────┴──────┴───────┴────────┴───────────┴───────┴────────┴──────┘")

    passing = [r for r in results if r.passes]
    if passing:
        best = max(passing, key=lambda r: r.monthly_return_usd)
        print(f"\n최적 레버리지: {best.leverage}x")
        print(f"  PF={best.profit_factor:.2f}, MDD={best.mdd_pct:.1f}%, 월수익=${best.monthly_return_usd:.2f}")
    else:
        # 조건 미충족 시 가장 안전한 것 선택
        best = min(results, key=lambda r: r.mdd_pct)
        print(f"\n경고: 모든 레버리지가 기준 미달 → 가장 낮은 MDD 레버리지 선택: {best.leverage}x")

    print()
    return best  # type: ignore[return-value]


# ──────────────────────────────────────────────
# 전략 파일 반영
# ──────────────────────────────────────────────
def apply_override(best: BacktestResult) -> None:
    if not OVERRIDE_PATH.exists():
        print(f"경고: {OVERRIDE_PATH} 없음 → 스킵")
        return

    data = json.loads(OVERRIDE_PATH.read_text())
    cfg = LEVERAGE_CONFIGS[best.leverage]
    data["funding_rate_strategy"] = {
        "enabled": True,
        "leverage": best.leverage,
        "funding_threshold": FUNDING_THRESHOLD,
        "sl_atr_multiplier": cfg["sl_atr"],
        "tp_atr_multiplier": cfg["tp_atr"],
        "max_hold_hours": MAX_HOLD_HOURS,
        "symbols": SYMBOLS,
        "backtest_total_return_pct": round(best.total_return_pct, 2),
        "backtest_mdd_pct": round(best.mdd_pct, 2),
        "backtest_profit_factor": round(best.profit_factor, 3) if best.profit_factor != float("inf") else 999,
        "backtest_win_rate": round(best.win_rate, 2),
        "backtest_monthly_usd": round(best.monthly_return_usd, 2),
    }
    OVERRIDE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"→ strategy_override.approved.json 업데이트 완료 (leverage={best.leverage}x)")


def write_strategy_module(best: BacktestResult) -> None:
    cfg = LEVERAGE_CONFIGS[best.leverage]
    code = f'''"""
펀딩비 역추세 전략 (자동 생성)
레버리지: {best.leverage}x  |  백테스트 PF: {best.profit_factor:.2f}  |  MDD: {best.mdd_pct:.1f}%
생성일: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
"""
from __future__ import annotations

# ── 전략 상수 ──────────────────────────────────────────────────────────────
LEVERAGE: int = {best.leverage}
FUNDING_THRESHOLD: float = {FUNDING_THRESHOLD}   # 0.015 %
SL_ATR_MULTIPLIER: float = {cfg["sl_atr"]}
TP_ATR_MULTIPLIER: float = {cfg["tp_atr"]}
MAX_HOLD_HOURS: int = {MAX_HOLD_HOURS}
TAKER_FEE_RATE: float = {TAKER_FEE_RATE}
SLIPPAGE_RATE: float = {SLIPPAGE_RATE}
MARGIN_BUFFER: float = {MARGIN_BUFFER}
SYMBOLS: list[str] = {SYMBOLS!r}


def position_size(capital_usd: float) -> float:
    """자본 × 레버리지 = 포지션 규모"""
    return capital_usd * LEVERAGE


def pnl(entry: float, exit_: float, side: str, capital_usd: float) -> float:
    """레버리지 적용 손익 (USD)"""
    size = position_size(capital_usd)
    if side == "long":
        chg = (exit_ - entry) / entry
    else:
        chg = (entry - exit_) / entry
    cost = (TAKER_FEE_RATE * 2 + SLIPPAGE_RATE) * LEVERAGE
    return (chg * LEVERAGE - cost) * capital_usd


def liquidation_price(entry: float, side: str) -> float:
    """강제청산 예상가"""
    liq_dist = entry / LEVERAGE * MARGIN_BUFFER
    return entry - liq_dist if side == "long" else entry + liq_dist


def sl_price(entry: float, atr: float, side: str) -> float:
    dist = atr * SL_ATR_MULTIPLIER
    return entry - dist if side == "long" else entry + dist


def tp_price(entry: float, atr: float, side: str) -> float:
    dist = atr * TP_ATR_MULTIPLIER
    return entry + dist if side == "long" else entry - dist


def signal(funding_rate: float) -> str | None:
    """펀딩비 역추세 진입 신호"""
    if funding_rate >= FUNDING_THRESHOLD:
        return "short"
    if funding_rate <= -FUNDING_THRESHOLD:
        return "long"
    return None
'''
    STRATEGY_FILE.write_text(code)
    print(f"→ quant_binance/funding_rate_strategy.py 레버리지 반영 완료 (leverage={best.leverage}x)")


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
def main() -> None:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - LOOKBACK_DAYS * 24 * 3600 * 1000

    print(f"펀딩비 역추세 전략 — 레버리지 백테스트 ({LOOKBACK_DAYS}일)")
    print(f"심볼: {', '.join(SYMBOLS)}")
    print(f"펀딩비 임계치: {FUNDING_THRESHOLD*100:.3f}%  |  수수료: {ROUND_TRIP_COST*100:.2f}%")
    print()

    # 심볼별 데이터 로드
    all_trades: dict[int, list[Trade]] = {lv: [] for lv in LEVERAGE_CONFIGS}

    for symbol in SYMBOLS:
        print(f"[{symbol}] 데이터 로드...")
        try:
            candles, funding = load_data(symbol, start_ms, now_ms)
        except Exception as e:
            print(f"  오류: {e} → 스킵")
            continue

        print(f"  캔들: {len(candles)}개  |  펀딩비: {len(funding)}개  |  신호: {sum(1 for f in funding if abs(f.rate) >= FUNDING_THRESHOLD)}개")

        for lv, cfg in LEVERAGE_CONFIGS.items():
            trades = backtest_symbol(
                symbol, candles, funding,
                leverage=lv,
                sl_atr_mult=cfg["sl_atr"],
                tp_atr_mult=cfg["tp_atr"],
            )
            all_trades[lv].extend(trades)

    # 메트릭 계산
    results: list[BacktestResult] = []
    for lv in sorted(LEVERAGE_CONFIGS):
        r = compute_metrics(all_trades[lv], lv, CAPITAL_USD)
        results.append(r)

    # 상세 출력
    for r in results:
        print(f"\n[{r.leverage}x] 최대연속손실={r.max_consec_losses}회  |  최악거래={r.worst_trade_pct:+.2f}%  |  청산={r.liquidations}건")

    best = print_results(results)

    # 전략 파일 적용
    apply_override(best)
    write_strategy_module(best)


if __name__ == "__main__":
    main()
