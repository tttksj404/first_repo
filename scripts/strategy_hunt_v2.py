"""
소자본 한탕 전략 탐색 v2 — 개선판
수수료: 0.16% + 슬리피지: 0.05% = 총 0.21% 편도 (왕복 0.42%)
"""
import json
import math
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path("/Users/tttksj/first_repo/quant_runtime/historical")
SYMBOLS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]
COST     = 0.0021  # 편도

# ─────────────────────────────────────────
def load(symbol, tf="1h"):
    with open(DATA_DIR / symbol / f"{tf}.json") as f:
        rows = json.load(f)
    for r in rows:
        r["ts"] = r["open_time"] / 1000
        r["o"]  = float(r["open_price"])
        r["h"]  = float(r["high_price"])
        r["l"]  = float(r["low_price"])
        r["c"]  = float(r["close_price"])
        r["v"]  = float(r["base_volume"])
    return rows

# ─────────────────────────────────────────
# 공통 지표
# ─────────────────────────────────────────
def atr_series(bars, p=14):
    out = [None] * len(bars)
    trs = [bars[0]["h"] - bars[0]["l"]]
    for i in range(1, len(bars)):
        trs.append(max(bars[i]["h"] - bars[i]["l"],
                       abs(bars[i]["h"] - bars[i-1]["c"]),
                       abs(bars[i]["l"] - bars[i-1]["c"])))
    for i in range(p-1, len(bars)):
        out[i] = sum(trs[i-p+1:i+1]) / p
    return out

def sma_series(vals, p):
    out = [None] * len(vals)
    for i in range(p-1, len(vals)):
        if all(vals[j] is not None for j in range(i-p+1, i+1)):
            out[i] = sum(vals[i-p+1:i+1]) / p
    return out

def ema_series(closes, p):
    out = [None] * len(closes)
    k = 2 / (p + 1)
    if len(closes) < p:
        return out
    out[p-1] = sum(closes[:p]) / p
    for i in range(p, len(closes)):
        out[i] = closes[i] * k + out[i-1] * (1 - k)
    return out

def bb_series(closes, p=20, mult=2.0):
    upper, mid, lower, bw = [None]*len(closes), [None]*len(closes), [None]*len(closes), [None]*len(closes)
    for i in range(p-1, len(closes)):
        w = closes[i-p+1:i+1]
        m = sum(w)/p
        s = math.sqrt(sum((x-m)**2 for x in w)/p)
        mid[i], upper[i], lower[i] = m, m+mult*s, m-mult*s
        bw[i] = (upper[i]-lower[i])/m if m else None
    return upper, mid, lower, bw

def adx_series(bars, p=14):
    out = [None] * len(bars)
    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(bars)):
        h, l = bars[i]["h"], bars[i]["l"]
        ph, pl, pc = bars[i-1]["h"], bars[i-1]["l"], bars[i-1]["c"]
        up = h - ph; down = pl - l
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        tr_list.append(max(h-l, abs(h-pc), abs(l-pc)))
    def wilder(lst):
        s = sum(lst[:p]); out2 = [s]
        for v in lst[p:]: s = s - s/p + v; out2.append(s)
        return out2
    sp = wilder(plus_dm); sm = wilder(minus_dm); st = wilder(tr_list)
    dx_list = []
    for a, b, t in zip(sp, sm, st):
        if t == 0: dx_list.append(0); continue
        dip, dim = 100*a/t, 100*b/t
        s = dip+dim
        dx_list.append(100*abs(dip-dim)/s if s else 0)
    for i in range(p*2-1, len(bars)):
        idx = i - p
        if idx >= p-1:
            out[i] = sum(dx_list[idx-p+1:idx+1]) / p
    return out

# ─────────────────────────────────────────
def stats(trades):
    if not trades: return {"n":0,"wr":0,"pf":0,"pnl":0}
    wins  = [t for t in trades if t > 0]
    loss  = [t for t in trades if t <= 0]
    gp = sum(wins); gl = abs(sum(loss))
    return {"n":len(trades), "wr":len(wins)/len(trades)*100,
            "pf": gp/gl if gl else float("inf"),
            "pnl": sum(trades)*100}

def monthly_est(pnl_pct, days, cap=70, lev=10):
    return cap * lev * (pnl_pct / days * 30) / 100 if days > 0 else 0

def simulate(entry, entry_dir, stop, target, bars_ahead, bars, idx):
    """멀티바 청산 시뮬레이터. bars_ahead 봉 동안 stop/target 체크 후 마지막봉 close로 청산"""
    for j in range(1, bars_ahead+1):
        if idx+j >= len(bars): break
        b = bars[idx+j]
        if entry_dir == 1:
            if b["l"] <= stop:    return (stop - entry) / entry
            if b["h"] >= target:  return (target - entry) / entry
        else:
            if b["h"] >= stop:    return (entry - stop) / entry
            if b["l"] <= target:  return (entry - target) / entry
    # time exit
    ep = bars[min(idx+bars_ahead, len(bars)-1)]["c"]
    return entry_dir * (ep*(1 - entry_dir*COST) - entry) / entry

COST = 0.0021

def print_result(name, sym_res, days):
    print(f"\n{'='*58}")
    print(f"전략명: {name}")
    print(f"{'='*58}")
    all_t = []
    for sym, t in sym_res.items():
        s = stats(t); all_t += t
        print(f"  {sym:<10}: 거래수={s['n']:>3}, 승률={s['wr']:>5.1f}%, "
              f"PF={s['pf']:>5.2f}, 총PnL%={s['pnl']:>+7.2f}%")
    s = stats(all_t)
    est = monthly_est(s["pnl"], days)
    print(f"  {'합산':<10}: 거래수={s['n']:>3}, 승률={s['wr']:>5.1f}%, "
          f"PF={s['pf']:>5.2f}, 총PnL%={s['pnl']:>+7.2f}%")
    print(f"  레버리지 10x 기준 월수익 추정($70): ${est:+.2f}")
    if s["pf"] >= 1.5 and s["n"] >= 20:
        v = "⭐편입"
    elif s["pf"] >= 1.2 and s["n"] >= 10:
        v = "앙상블후보"
    else:
        v = "탈락"
    print(f"  판정: {v}")
    return s, v

# ═══════════════════════════════════════════
# 전략 1: 극단 변동성 역추세 (완화: ATR×2, 5봉 보유)
# ═══════════════════════════════════════════
def s1_mean_reversion(bars):
    atr  = atr_series(bars, 14)
    c    = [b["c"] for b in bars]
    ema  = ema_series(c, 50)
    trades = []
    for i in range(20, len(bars)-6):
        if atr[i] is None or ema[i] is None: continue
        move = abs(bars[i]["c"] - bars[i]["o"])
        if move < atr[i] * 2.0: continue          # ATR×3 → ×2 완화

        spike_dir = 1 if bars[i]["c"] > bars[i]["o"] else -1
        ed = -spike_dir  # 역방향

        entry = bars[i+1]["o"] * (1 + ed*COST)
        if ed == 1:
            stop   = bars[i]["l"] * (1 - COST)
            target = ema[i] if ema[i] > entry * 1.005 else entry * 1.015
        else:
            stop   = bars[i]["h"] * (1 + COST)
            target = ema[i] if ema[i] < entry * 0.995 else entry * 0.985

        if ed == 1 and (target <= entry or stop >= entry): continue
        if ed == -1 and (target >= entry or stop <= entry): continue

        pnl = simulate(entry, ed, stop, target, 5, bars, i+1)
        trades.append(pnl)
    return trades

# ═══════════════════════════════════════════
# 전략 2: BB 스퀴즈 브레이크아웃 (개선: 롤링 최솟값, 6봉 보유)
# ═══════════════════════════════════════════
def s2_bb_squeeze(bars):
    c = [b["c"] for b in bars]
    upper, mid, lower, bw = bb_series(c, 20)
    adx = adx_series(bars, 14)
    trades = []

    for i in range(30, len(bars)-7):
        if bw[i] is None or adx[i] is None: continue
        # 스퀴즈: 직전 5봉 내에 BW 최솟값이 있고, 현재봉에서 확장
        w20 = [bw[j] for j in range(i-20, i) if bw[j] is not None]
        if len(w20) < 15: continue
        min_bw = min(w20)
        # 직전 5봉 내에 min_bw가 있었는지
        recent_min = any(bw[j] == min_bw for j in range(i-5, i) if bw[j] is not None)
        if not recent_min: continue
        if bw[i] <= min_bw * 1.05: continue  # 아직 충분히 확장 안됨
        if adx[i] < 18: continue

        curr = bars[i]; nxt = bars[i+1]
        ed = 1 if curr["c"] > mid[i] else -1
        entry = nxt["o"] * (1 + ed*COST)

        if ed == 1:
            stop   = mid[i] * (1 - COST)
            target = upper[i] * (1 - COST)
        else:
            stop   = mid[i] * (1 + COST)
            target = lower[i] * (1 + COST)

        if ed == 1 and (target <= entry or stop >= entry): continue
        if ed == -1 and (target >= entry or stop <= entry): continue

        pnl = simulate(entry, ed, stop, target, 6, bars, i+1)
        trades.append(pnl)
    return trades

# ═══════════════════════════════════════════
# 전략 3: 세션 바이어스 (개선: 강한 방향성만 + 손절 추가)
# ═══════════════════════════════════════════
def s3_session_bias(bars):
    atr = atr_series(bars, 14)
    trades = []
    SESSIONS = [(0, "Asia"), (13, "US")]
    HOLD = 3  # 3봉

    for i in range(14, len(bars)-HOLD-1):
        if atr[i] is None: continue
        hour = datetime.fromtimestamp(bars[i]["ts"], tz=timezone.utc).hour
        if hour not in (0, 13): continue

        curr = bars[i]
        body = abs(curr["c"] - curr["o"])
        # 강한 방향성: 봉 실체가 ATR의 40% 이상
        if body < atr[i] * 0.4: continue
        # 위꼬리/아래꼬리 비율 확인 (방향성이 명확한 캔들)
        if curr["c"] > curr["o"]:
            ed = 1
            wick_ratio = (curr["h"] - curr["c"]) / body if body else 1
        else:
            ed = -1
            wick_ratio = (curr["o"] - curr["l"]) / body if body else 1
        if wick_ratio > 0.5: continue  # 반대꼬리가 너무 길면 제외

        entry = bars[i+1]["o"] * (1 + ed*COST)
        # 손절: ATR의 1.5배
        if ed == 1:
            stop   = entry - atr[i] * 1.5
            target = entry + atr[i] * 2.0
        else:
            stop   = entry + atr[i] * 1.5
            target = entry - atr[i] * 2.0

        pnl = simulate(entry, ed, stop, target, HOLD, bars, i+1)
        trades.append(pnl)
    return trades

# ═══════════════════════════════════════════
# 전략 4: N봉 반전 (N=2로 완화, 4봉 보유)
# ═══════════════════════════════════════════
def s4_nbar_reversal(bars, n=2):
    atr = atr_series(bars, 14)
    trades = []

    for i in range(n+5, len(bars)-5):
        if atr[i] is None: continue
        curr = bars[i]

        # 연속 하락 후 첫 양봉
        bearish_run = all(bars[i-j]["c"] < bars[i-j]["o"] for j in range(1, n+1))
        bull_entry  = curr["c"] > curr["o"]

        # 연속 상승 후 첫 음봉
        bullish_run = all(bars[i-j]["c"] > bars[i-j]["o"] for j in range(1, n+1))
        bear_entry  = curr["c"] < curr["o"]

        # 거래량 확인
        avg_vol = sum(bars[i-k]["v"] for k in range(1, 11)) / 10
        if curr["v"] < avg_vol: continue

        if bearish_run and bull_entry:
            ed = 1
            low_n  = min(bars[i-j]["l"] for j in range(1, n+1))
            high_n = max(bars[i-j]["h"] for j in range(1, n+1))
            stop   = low_n * (1 - COST)
            target = curr["h"] + (curr["h"] - low_n) * 0.618
        elif bullish_run and bear_entry:
            ed = -1
            high_n = max(bars[i-j]["h"] for j in range(1, n+1))
            low_n  = min(bars[i-j]["l"] for j in range(1, n+1))
            stop   = high_n * (1 + COST)
            target = curr["l"] - (high_n - curr["l"]) * 0.618
        else:
            continue

        entry = bars[i+1]["o"] * (1 + ed*COST)
        if ed == 1 and (target <= entry or stop >= entry): continue
        if ed == -1 and (target >= entry or stop <= entry): continue

        pnl = simulate(entry, ed, stop, target, 4, bars, i+1)
        trades.append(pnl)
    return trades

# ═══════════════════════════════════════════
# 전략 5: 이상 거래량 (개선: 2.5배로 완화, 방향+모멘텀 확인)
# ═══════════════════════════════════════════
def s5_volume_spike(bars):
    atr = atr_series(bars, 14)
    trades = []
    HOLD = 6

    for i in range(20, len(bars)-HOLD-1):
        if atr[i] is None: continue
        avg_vol = sum(bars[i-k]["v"] for k in range(1, 21)) / 20
        if bars[i]["v"] < avg_vol * 2.5: continue

        curr = bars[i]
        body = abs(curr["c"] - curr["o"])
        # 방향성이 명확한 스파이크 (실체 > ATR*0.5)
        if body < atr[i] * 0.5: continue

        ed = 1 if curr["c"] > curr["o"] else -1
        # 이전 3봉 추세와 동일 방향이어야 모멘텀 확인
        prev_dir = 1 if bars[i-1]["c"] > bars[i-3]["o"] else -1
        if prev_dir != ed: continue

        entry = bars[i+1]["o"] * (1 + ed*COST)
        if ed == 1:
            stop   = curr["l"] * (1 - COST)
            target = entry + body * 2.0
        else:
            stop   = curr["h"] * (1 + COST)
            target = entry - body * 2.0

        if ed == 1 and (target <= entry or stop >= entry): continue
        if ed == -1 and (target >= entry or stop <= entry): continue

        pnl = simulate(entry, ed, stop, target, HOLD, bars, i+1)
        trades.append(pnl)
    return trades

# ═══════════════════════════════════════════
# 전략 6: 주말 패턴 (개선: 금~월 갭 방향 + 손절 추가)
# ═══════════════════════════════════════════
def s6_weekend(bars):
    atr = atr_series(bars, 14)
    trades = []

    for i in range(14, len(bars)-25):
        if atr[i] is None: continue
        ts   = bars[i]["ts"]
        dt   = datetime.fromtimestamp(ts, tz=timezone.utc)
        # 월요일 00:00~12:00 UTC 사이 임의 시간 (주말 후 첫 반응)
        if dt.weekday() != 0 or dt.hour > 12: continue

        curr = bars[i]
        # 금요일 종가를 찾아 갭 방향 확인
        fri_close = None
        for j in range(i-1, max(i-48, 0), -1):
            d = datetime.fromtimestamp(bars[j]["ts"], tz=timezone.utc)
            if d.weekday() == 4:  # 금요일
                fri_close = bars[j]["c"]
                break
        if fri_close is None: continue

        # 월요일 현재가 vs 금요일 종가 → 갭 방향
        gap = (curr["c"] - fri_close) / fri_close
        if abs(gap) < 0.003: continue  # 갭이 너무 작으면 스킵

        ed = 1 if gap > 0 else -1
        entry  = bars[i+1]["o"] * (1 + ed*COST)
        stop   = entry - ed * atr[i] * 2.0
        target = entry + ed * atr[i] * 3.0

        pnl = simulate(entry, ed, stop, target, 12, bars, i+1)
        trades.append(pnl)
    return trades

# ═══════════════════════════════════════════
# 전략 7 (보너스): 펀딩비 역추세 재현 (high funding → short)
# ─ 로컬 funding_rates.json 활용
# ═══════════════════════════════════════════
def s7_funding_contrarian(bars, symbol):
    fr_path = DATA_DIR / symbol / "funding_rates.json"
    if not fr_path.exists(): return []
    with open(fr_path) as f:
        fr_data = json.load(f)

    # 펀딩비 딕셔너리: ts → rate
    fr_map = {}
    for row in fr_data:
        if isinstance(row, dict):
            ts  = row.get("fundingTime", row.get("time", 0))
            rate = float(row.get("fundingRate", row.get("rate", 0)))
            fr_map[int(ts) // 1000] = rate

    atr = atr_series(bars, 14)
    trades = []
    THRESHOLD = 0.0005  # 0.05% 이상

    for i in range(14, len(bars)-5):
        if atr[i] is None: continue
        ts = int(bars[i]["ts"])
        # 가장 가까운 펀딩 타임 찾기 (±4시간)
        rate = None
        for delta in range(-14400, 14401, 3600):
            if ts + delta in fr_map:
                rate = fr_map[ts + delta]
                break
        if rate is None: continue
        if abs(rate) < THRESHOLD: continue

        # 높은 양의 펀딩비 → 매도 과열 → 숏 포지션 많음 → 반등 기대
        ed = -1 if rate > 0 else 1  # 펀딩비 방향 역추세
        entry = bars[i+1]["o"] * (1 + ed*COST)

        if ed == 1:
            stop   = bars[i]["l"] * (1 - COST)
            target = entry + atr[i] * 2.5
        else:
            stop   = bars[i]["h"] * (1 + COST)
            target = entry - atr[i] * 2.5

        if ed == 1 and (target <= entry or stop >= entry): continue
        if ed == -1 and (target >= entry or stop <= entry): continue

        pnl = simulate(entry, ed, stop, target, 8, bars, i+1)
        trades.append(pnl)
    return trades

# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
def main():
    print("=" * 58)
    print("소자본 한탕 전략 탐색 v2 — 개선판")
    print(f"수수료+슬리피지: {COST*2*100:.2f}% 왕복")
    print("=" * 58)

    data = {}
    days = 0
    for sym in SYMBOLS:
        bars = load(sym)
        data[sym] = bars
        if bars:
            days = max(days, (bars[-1]["ts"] - bars[0]["ts"]) / 86400)
    print(f"데이터 기간: ~{days:.0f}일\n")

    strategies = [
        ("전략1 극단변동성 역추세 (ATR×2, 5봉)", lambda bars, sym: s1_mean_reversion(bars)),
        ("전략2 BB스퀴즈 브레이크아웃 (개선)", lambda bars, sym: s2_bb_squeeze(bars)),
        ("전략3 세션바이어스 (강한방향+손절)", lambda bars, sym: s3_session_bias(bars)),
        ("전략4 N봉반전 (N=2, 4봉)", lambda bars, sym: s4_nbar_reversal(bars)),
        ("전략5 이상거래량 (2.5×모멘텀확인)", lambda bars, sym: s5_volume_spike(bars)),
        ("전략6 주말갭방향 (개선)", lambda bars, sym: s6_weekend(bars)),
        ("전략7 펀딩비역추세 (보너스)", lambda bars, sym: s7_funding_contrarian(bars, sym)),
    ]

    all_results = []
    for name, fn in strategies:
        sym_res = {}
        for sym in SYMBOLS:
            try:
                sym_res[sym] = fn(data[sym], sym)
            except Exception as e:
                print(f"  [{sym}] {name} 오류: {e}")
                sym_res[sym] = []
        s, v = print_result(name, sym_res, days)
        all_results.append((name, s, v))

    # ─── 최종 요약 ───
    print(f"\n{'='*58}")
    print("최종 요약 — 한탕 가능 전략 TOP 3")
    print("=" * 58)
    top  = [(n,s) for n,s,v in all_results if v == "⭐편입"]
    cand = [(n,s) for n,s,v in all_results if v == "앙상블후보"]

    if top:
        top_sorted = sorted(top, key=lambda x: x[1]["pf"], reverse=True)
        for rank, (n, s) in enumerate(top_sorted[:3], 1):
            est = monthly_est(s["pnl"], days)
            print(f"\n  #{rank} {n}")
            print(f"     PF={s['pf']:.2f} | 승률={s['wr']:.1f}% | "
                  f"거래수={s['n']} | 월수익추정=${est:+.2f}")
    else:
        print("\n  PF≥1.5 충족 전략 없음")

    if cand:
        print("\n[앙상블 후보]")
        for n, s in sorted(cand, key=lambda x: x[1]["pf"], reverse=True):
            est = monthly_est(s["pnl"], days)
            print(f"  {n}")
            print(f"     PF={s['pf']:.2f} | 승률={s['wr']:.1f}% | 월수익추정=${est:+.2f}")

    # PF 기준 전체 랭킹
    print("\n[전체 PF 랭킹]")
    for rank, (n, s, v) in enumerate(
        sorted(all_results, key=lambda x: x[1]["pf"], reverse=True), 1
    ):
        print(f"  {rank}. PF={s['pf']:>5.2f} | {v} | {n}")

    print("\n[앙상블 조합 추천]")
    print("  상관관계 낮은 조합 = 시간 기반(세션/주말) × 구조 기반(N봉/BB스퀴즈)")
    print("  → 신호 중복 최소화, 드로다운 분산 효과")

if __name__ == "__main__":
    main()
