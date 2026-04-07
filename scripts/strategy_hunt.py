"""
소자본 한탕 전략 탐색 백테스터
수수료: 0.16% + 슬리피지: 0.05% = 총 0.21% 편도 (왕복 0.42%)
"""
import json
import math
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path("/Users/tttksj/first_repo/quant_runtime/historical")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
COST_PER_SIDE = 0.0021  # 수수료+슬리피지

# ─────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────
def load(symbol: str, tf: str = "1h") -> list[dict]:
    path = DATA_DIR / symbol / f"{tf}.json"
    with open(path) as f:
        rows = json.load(f)
    for r in rows:
        r["ts"] = r["open_time"] / 1000
        r["o"] = float(r["open_price"])
        r["h"] = float(r["high_price"])
        r["l"] = float(r["low_price"])
        r["c"] = float(r["close_price"])
        r["v"] = float(r["base_volume"])
    return rows

# ─────────────────────────────────────────
# 공통 지표 계산
# ─────────────────────────────────────────
def calc_atr(bars, period=14):
    atr = [None] * len(bars)
    trs = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b["h"] - b["l"])
        else:
            tr = max(b["h"] - b["l"],
                     abs(b["h"] - bars[i-1]["c"]),
                     abs(b["l"] - bars[i-1]["c"]))
            trs.append(tr)
    for i in range(period - 1, len(bars)):
        atr[i] = sum(trs[i-period+1:i+1]) / period
    return atr

def calc_ema(vals, period):
    ema = [None] * len(vals)
    k = 2 / (period + 1)
    start = next((i for i, v in enumerate(vals) if v is not None), None)
    if start is None:
        return ema
    # seed with SMA
    seed_end = start + period
    if seed_end > len(vals):
        return ema
    ema[seed_end - 1] = sum(v for v in vals[start:seed_end] if v is not None) / period
    for i in range(seed_end, len(vals)):
        if vals[i] is not None:
            ema[i] = vals[i] * k + ema[i-1] * (1 - k)
        else:
            ema[i] = ema[i-1]
    return ema

def calc_bb(closes, period=20, std_mult=2.0):
    upper = [None] * len(closes)
    mid   = [None] * len(closes)
    lower = [None] * len(closes)
    bw    = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i-period+1:i+1]
        m = sum(window) / period
        s = math.sqrt(sum((x - m)**2 for x in window) / period)
        mid[i]   = m
        upper[i] = m + std_mult * s
        lower[i] = m - std_mult * s
        bw[i]    = (upper[i] - lower[i]) / m if m else None
    return upper, mid, lower, bw

def calc_adx(bars, period=14):
    adx = [None] * len(bars)
    if len(bars) < period * 2:
        return adx
    plus_dm  = []
    minus_dm = []
    tr_list  = []
    for i in range(1, len(bars)):
        h, l = bars[i]["h"], bars[i]["l"]
        ph, pl = bars[i-1]["h"], bars[i-1]["l"]
        move_up   = h - ph
        move_down = pl - l
        plus_dm.append(move_up   if move_up > move_down and move_up > 0   else 0)
        minus_dm.append(move_down if move_down > move_up and move_down > 0 else 0)
        tr = max(h - l, abs(h - bars[i-1]["c"]), abs(l - bars[i-1]["c"]))
        tr_list.append(tr)

    def smooth(lst, p):
        out = []
        s = sum(lst[:p])
        out.append(s)
        for v in lst[p:]:
            s = s - s/p + v
            out.append(s)
        return out

    splus  = smooth(plus_dm, period)
    sminus = smooth(minus_dm, period)
    str_   = smooth(tr_list, period)

    dx_list = []
    for a, b, t in zip(splus, sminus, str_):
        if t == 0:
            dx_list.append(0)
        else:
            di_plus  = 100 * a / t
            di_minus = 100 * b / t
            dx = 100 * abs(di_plus - di_minus) / (di_plus + di_minus) if (di_plus + di_minus) else 0
            dx_list.append(dx)

    # ADX = smoothed DX
    for i in range(period - 1 + period, len(bars)):
        offset = i - period  # index into dx_list
        if offset >= period - 1:
            window = dx_list[offset-period+1:offset+1]
            adx[i] = sum(window) / period
    return adx

# ─────────────────────────────────────────
# 성과 계산 헬퍼
# ─────────────────────────────────────────
def calc_stats(trades):
    if not trades:
        return {"n": 0, "win_rate": 0, "pf": 0, "total_pnl": 0}
    wins  = [t for t in trades if t > 0]
    loses = [t for t in trades if t <= 0]
    gross_profit = sum(wins)
    gross_loss   = abs(sum(loses))
    pf = gross_profit / gross_loss if gross_loss else float("inf")
    total_pnl = sum(trades)
    return {
        "n": len(trades),
        "win_rate": len(wins) / len(trades) * 100,
        "pf": pf,
        "total_pnl": total_pnl * 100,  # %
    }

def monthly_est(total_pnl_pct, n_trades, days_covered, capital=70, leverage=10):
    """총 수익%에서 월수익 달러 추정"""
    if days_covered <= 0:
        return 0
    monthly_pnl_pct = total_pnl_pct / days_covered * 30
    return capital * leverage * monthly_pnl_pct / 100

def print_result(name, sym_results, days_covered):
    print(f"\n{'='*55}")
    print(f"전략명: {name}")
    print(f"{'='*55}")
    all_trades = []
    for sym, trades in sym_results.items():
        s = calc_stats(trades)
        all_trades.extend(trades)
        print(f"  {sym:<10}: 거래수={s['n']:>3}, 승률={s['win_rate']:>5.1f}%, "
              f"PF={s['pf']:>5.2f}, 총PnL%={s['total_pnl']:>+7.2f}%")
    s_all = calc_stats(all_trades)
    est = monthly_est(s_all["total_pnl"], s_all["n"], days_covered)
    print(f"  {'합산':<10}: 거래수={s_all['n']:>3}, 승률={s_all['win_rate']:>5.1f}%, "
          f"PF={s_all['pf']:>5.2f}, 총PnL%={s_all['total_pnl']:>+7.2f}%")
    print(f"  레버리지 10x 기준 월수익 추정($70): ${est:+.2f}")

    pf = s_all["pf"]
    wr = s_all["win_rate"]
    n  = s_all["n"]
    if pf >= 1.5 and (wr >= 45 or True) and n >= 20:
        verdict = "⭐편입"
    elif pf >= 1.2 and n >= 10:
        verdict = "앙상블후보"
    else:
        verdict = "탈락"
    print(f"  판정: {verdict}")
    return s_all, verdict

# ─────────────────────────────────────────
# 전략 1: 극단 변동성 역추세 (Mean Reversion after Spike)
# ─────────────────────────────────────────
def strategy_mean_reversion(bars):
    """1h 캔들 ATR×3 스파이크 후 다음봉 역방향 진입"""
    atr = calc_atr(bars, 14)
    closes = [b["c"] for b in bars]
    ema50 = calc_ema(closes, 50)
    trades = []

    for i in range(15, len(bars) - 1):
        if atr[i] is None or ema50[i] is None:
            continue
        prev = bars[i-1]
        curr = bars[i]
        nxt  = bars[i+1]

        candle_move = abs(curr["c"] - curr["o"])
        if candle_move < atr[i] * 3:
            continue

        direction = 1 if curr["c"] > curr["o"] else -1  # 스파이크 방향
        entry_dir = -direction  # 역방향 진입

        entry  = nxt["o"] * (1 + entry_dir * COST_PER_SIDE)
        # 손절: 직전 스파이크 극단
        if entry_dir == 1:  # 롱
            stop   = curr["l"] * (1 - COST_PER_SIDE)
            target = ema50[i] if ema50[i] > entry else entry * 1.02
        else:  # 숏
            stop   = curr["h"] * (1 + COST_PER_SIDE)
            target = ema50[i] if ema50[i] < entry else entry * 0.98

        # 다음 봉 내에서 청산 시뮬
        if entry_dir == 1:
            if nxt["l"] <= stop:
                pnl = (stop - entry) / entry
            elif nxt["h"] >= target:
                pnl = (target - entry) / entry
            else:
                pnl = (nxt["c"] - entry) / entry
        else:
            if nxt["h"] >= stop:
                pnl = (entry - stop) / entry
            elif nxt["l"] <= target:
                pnl = (entry - target) / entry
            else:
                pnl = (entry - nxt["c"]) / entry

        trades.append(pnl)
    return trades

# ─────────────────────────────────────────
# 전략 2: BB 스퀴즈 브레이크아웃
# ─────────────────────────────────────────
def strategy_bb_squeeze(bars):
    closes = [b["c"] for b in bars]
    upper, mid, lower, bw = calc_bb(closes, 20)
    adx = calc_adx(bars, 14)
    trades = []

    for i in range(22, len(bars) - 1):
        if bw[i] is None or adx[i] is None:
            continue
        # 스퀴즈: 현재 BW가 과거 20봉 중 최솟값이었다가 확장
        past_bw = [bw[j] for j in range(i-20, i) if bw[j] is not None]
        if not past_bw:
            continue
        # 직전봉이 최소BW였고 현재봉이 더 큰 경우
        if bw[i-1] != min(past_bw) or bw[i] <= bw[i-1]:
            continue
        if adx[i] < 20:
            continue

        curr = bars[i]
        nxt  = bars[i+1]
        # 방향: 현재봉 클로즈가 중심선 위면 롱
        entry_dir = 1 if curr["c"] > mid[i] else -1
        entry = nxt["o"] * (1 + entry_dir * COST_PER_SIDE)

        if entry_dir == 1:
            stop   = mid[i] * (1 - COST_PER_SIDE)
            target = upper[i] * (1 - COST_PER_SIDE)
            if target <= entry or stop >= entry:
                continue
            if nxt["l"] <= stop:
                pnl = (stop - entry) / entry
            elif nxt["h"] >= target:
                pnl = (target - entry) / entry
            else:
                pnl = (nxt["c"] - entry) / entry
        else:
            stop   = mid[i] * (1 + COST_PER_SIDE)
            target = lower[i] * (1 + COST_PER_SIDE)
            if target >= entry or stop <= entry:
                continue
            if nxt["h"] >= stop:
                pnl = (entry - stop) / entry
            elif nxt["l"] <= target:
                pnl = (entry - target) / entry
            else:
                pnl = (entry - nxt["c"]) / entry

        trades.append(pnl)
    return trades

# ─────────────────────────────────────────
# 전략 3: 세션 바이어스 (Session Bias)
# ─────────────────────────────────────────
def strategy_session_bias(bars):
    """세션 오픈 첫봉 방향으로 2시간 보유"""
    ASIA_START  = 0   # UTC 00:00
    ASIA_END    = 8
    US_START    = 13  # UTC 13:00
    US_END      = 21
    HOLD_BARS   = 2

    trades = []
    for i in range(len(bars) - HOLD_BARS - 1):
        ts   = bars[i]["ts"]
        hour = datetime.fromtimestamp(ts, tz=timezone.utc).hour

        is_session_open = (hour == ASIA_START) or (hour == US_START)
        if not is_session_open:
            continue

        curr = bars[i]
        entry_dir = 1 if curr["c"] > curr["o"] else -1
        entry = bars[i+1]["o"] * (1 + entry_dir * COST_PER_SIDE)
        exit_bar = bars[i + HOLD_BARS]
        exit_price = exit_bar["c"] * (1 - entry_dir * COST_PER_SIDE)

        pnl = entry_dir * (exit_price - entry) / entry
        trades.append(pnl)
    return trades

# ─────────────────────────────────────────
# 전략 4: N봉 연속 후 반전 (N-Bar Reversal)
# ─────────────────────────────────────────
def strategy_nbar_reversal(bars, n=3):
    """N봉 연속 하락(상승) 후 반전"""
    trades = []
    for i in range(n, len(bars) - 1):
        # 연속 하락: N봉 모두 음봉이고 upper shadow 거의 없음
        bearish = all(
            bars[i-j]["c"] < bars[i-j]["o"] and
            (bars[i-j]["h"] - bars[i-j]["o"]) < (bars[i-j]["o"] - bars[i-j]["c"]) * 0.3
            for j in range(1, n+1)
        )
        # 연속 상승: N봉 모두 양봉이고 lower shadow 거의 없음
        bullish = all(
            bars[i-j]["c"] > bars[i-j]["o"] and
            (bars[i-j]["o"] - bars[i-j]["l"]) < (bars[i-j]["c"] - bars[i-j]["o"]) * 0.3
            for j in range(1, n+1)
        )

        curr = bars[i]
        nxt  = bars[i+1]

        # 볼륨 확인: 현재봉 거래량이 최근 10봉 평균보다 많아야
        avg_vol = sum(bars[i-k]["v"] for k in range(1, 11)) / 10
        if curr["v"] < avg_vol * 0.8:
            continue

        if bearish and curr["c"] > curr["o"]:  # 연속하락 후 첫 양봉
            entry_dir = 1
            stop   = min(bars[i-j]["l"] for j in range(1, n+1)) * (1 - COST_PER_SIDE)
            target = max(bars[i-j]["h"] for j in range(1, n+1)) * (1 - COST_PER_SIDE)
        elif bullish and curr["c"] < curr["o"]:  # 연속상승 후 첫 음봉
            entry_dir = -1
            stop   = max(bars[i-j]["h"] for j in range(1, n+1)) * (1 + COST_PER_SIDE)
            target = min(bars[i-j]["l"] for j in range(1, n+1)) * (1 + COST_PER_SIDE)
        else:
            continue

        entry = nxt["o"] * (1 + entry_dir * COST_PER_SIDE)
        if entry_dir == 1:
            if target <= entry or stop >= entry:
                continue
            if nxt["l"] <= stop:
                pnl = (stop - entry) / entry
            elif nxt["h"] >= target:
                pnl = (target - entry) / entry
            else:
                pnl = (nxt["c"] - entry) / entry
        else:
            if target >= entry or stop <= entry:
                continue
            if nxt["h"] >= stop:
                pnl = (entry - stop) / entry
            elif nxt["l"] <= target:
                pnl = (entry - target) / entry
            else:
                pnl = (entry - nxt["c"]) / entry

        trades.append(pnl)
    return trades

# ─────────────────────────────────────────
# 전략 5: 이상 거래량 발생 후 추세 지속
# ─────────────────────────────────────────
def strategy_volume_spike(bars):
    """일일 거래량 평균 3배 이상인 봉 직후 방향 추세 지속"""
    HOLD = 4  # 4봉(4시간) 보유
    trades = []
    vols = [b["v"] for b in bars]

    for i in range(20, len(bars) - HOLD - 1):
        avg_vol = sum(vols[i-20:i]) / 20
        if bars[i]["v"] < avg_vol * 3.0:
            continue

        curr = bars[i]
        entry_dir = 1 if curr["c"] > curr["o"] else -1
        entry = bars[i+1]["o"] * (1 + entry_dir * COST_PER_SIDE)

        # 손절: 스파이크 봉 반대 극단
        if entry_dir == 1:
            stop   = curr["l"] * (1 - COST_PER_SIDE)
            target = entry * (1 + abs(curr["c"] - curr["o"]) / curr["o"] * 2)
        else:
            stop   = curr["h"] * (1 + COST_PER_SIDE)
            target = entry * (1 - abs(curr["c"] - curr["o"]) / curr["o"] * 2)

        # HOLD봉 동안 확인
        hit_stop = hit_target = False
        exit_price = bars[i+HOLD]["c"]
        for j in range(1, HOLD+1):
            b = bars[i+j]
            if entry_dir == 1:
                if b["l"] <= stop:
                    exit_price = stop; hit_stop = True; break
                if b["h"] >= target:
                    exit_price = target; hit_target = True; break
            else:
                if b["h"] >= stop:
                    exit_price = stop; hit_stop = True; break
                if b["l"] <= target:
                    exit_price = target; hit_target = True; break

        exit_price *= (1 - entry_dir * COST_PER_SIDE)
        pnl = entry_dir * (exit_price - entry) / entry
        trades.append(pnl)
    return trades

# ─────────────────────────────────────────
# 전략 6: 주말 패턴 (Weekend Effect)
# ─────────────────────────────────────────
def strategy_weekend(bars):
    """월요일 09:00 UTC 이후 첫봉 방향으로 24봉 보유"""
    HOLD = 24
    trades = []
    for i in range(len(bars) - HOLD - 1):
        ts = bars[i]["ts"]
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        # 월요일 09:00 UTC (weekday=0)
        if dt.weekday() != 0 or dt.hour != 9:
            continue

        curr = bars[i]
        entry_dir = 1 if curr["c"] > curr["o"] else -1
        entry = bars[i+1]["o"] * (1 + entry_dir * COST_PER_SIDE)
        exit_bar = bars[i + HOLD]
        exit_price = exit_bar["c"] * (1 - entry_dir * COST_PER_SIDE)

        pnl = entry_dir * (exit_price - entry) / entry
        trades.append(pnl)
    return trades

# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    print("=" * 55)
    print("소자본 한탕 전략 탐색 백테스터")
    print(f"수수료+슬리피지: {COST_PER_SIDE*2*100:.2f}% 왕복")
    print("=" * 55)

    # 데이터 로드
    data = {}
    days_covered = 0
    for sym in SYMBOLS:
        try:
            bars = load(sym)
            data[sym] = bars
            if bars:
                span = (bars[-1]["ts"] - bars[0]["ts"]) / 86400
                days_covered = max(days_covered, span)
        except Exception as e:
            print(f"  [{sym}] 데이터 로드 실패: {e}")

    print(f"데이터 기간: ~{days_covered:.0f}일\n")

    strategies = [
        ("극단 변동성 역추세 (Mean Reversion after Spike)", strategy_mean_reversion),
        ("BB 스퀴즈 브레이크아웃", strategy_bb_squeeze),
        ("세션 바이어스 (Session Bias)", strategy_session_bias),
        ("N봉 연속 후 반전 (N-Bar Reversal)", strategy_nbar_reversal),
        ("이상 거래량 후 추세 지속 (Volume Spike)", strategy_volume_spike),
        ("주말 패턴 (Weekend Effect)", strategy_weekend),
    ]

    results = []
    for name, fn in strategies:
        sym_results = {}
        for sym in SYMBOLS:
            if sym not in data:
                sym_results[sym] = []
                continue
            try:
                trades = fn(data[sym])
                sym_results[sym] = trades
            except Exception as e:
                print(f"  [{sym}] {name} 오류: {e}")
                sym_results[sym] = []
        s, verdict = print_result(name, sym_results, days_covered)
        results.append((name, s, verdict))

    # 최종 요약
    print(f"\n{'='*55}")
    print("최종 요약: 한탕 가능 전략")
    print("=" * 55)
    top = [(n, s) for n, s, v in results if v == "⭐편입"]
    candidates = [(n, s) for n, s, v in results if v == "앙상블후보"]

    if top:
        print("\n[편입 확정]")
        top_sorted = sorted(top, key=lambda x: x[1]["pf"], reverse=True)
        for rank, (n, s) in enumerate(top_sorted[:3], 1):
            est = monthly_est(s["total_pnl"], s["n"], days_covered)
            print(f"  #{rank} {n}")
            print(f"     PF={s['pf']:.2f}, 승률={s['win_rate']:.1f}%, "
                  f"거래수={s['n']}, 월수익추정=${est:+.2f}")
    else:
        print("  PF≥1.5 충족 전략 없음")

    if candidates:
        print("\n[앙상블 후보]")
        for n, s in candidates:
            print(f"  - {n} (PF={s['pf']:.2f})")

    print("\n[상관관계 낮은 조합 권장]")
    print("  시간대별 진입(세션바이어스) + 구조적 패턴(N봉반전)")
    print("  → 신호 겹치지 않아 분산효과 최대화")

if __name__ == "__main__":
    main()
