# 부분 재투자 검증 + Paper Bot 최종 보고서

**작성일**: 2026-04-26
**사용자 가설**: "10x 도박에서 벌면 40%만 safe pocket으로 빼두고 60%는 재투자"

---

## 1. 핵심 발견 — 사용자 직관 vs 수학

**60% 재투자는 백테스트에서 V0(0% 재투자, 모두 빼두기)에 압도적으로 패배**합니다.

### S3 (vol_expansion + L4 NoSL/TP+500/신호종료) 기준 — 71 trades, 청산 9.9%

| 변종 | final | median | p25 | **p99 (잭팟)** | **MC ruin** |
|---|---:|---:|---:|---:|---:|
| **🏆 V0: 0% 재투자 (전부 safe)** | **$392** | **$403** | $254 | $897 | **4.8%** ✅ |
| V1: 30% 재투자 | $41 | $53 | $11 | $2,254 | 48.7% |
| V1: 40% 재투자 | $36 | $47 | $10 | $3,669 | 51.3% |
| V1: 60% 재투자 (사용자 제안) | $26 | $34 | $7 | **$8,891** | 59.3% |
| V1: 70% 재투자 | $20 | $27 | $5 | $12,613 | 64.4% |
| V5: refill 60% | $26 | $24 | $6 | $14,616 | 72.7% |

### 왜 60% 재투자가 망하는가
```
마진 = working_capital (동적 증가)
     ↓
이긴 후: 마진 커짐 → 다음 win 더 큼 (좋음)
     ↓
하지만 71 trades 중 7건 (10%) 청산 발생
     ↓
청산 시: working_capital의 100% 손실
     ↓
첫 청산이 게임 끝 → 이후 trade 모두 skip
```

이건 정확히 **Kelly Criterion + Risk of Ruin** 수학입니다. 풀 켈리는 한 번의 청산이 모든 걸 끝내고, 부분 켈리(낮은 reinvest)는 변동성 ↓, 중앙값 ↑.

---

## 2. 검증된 최적 로직 — V0 (Floor + All-to-Safe)

```python
# 핵심 알고리즘 (V0)
if pnl > 0:
    safe_pocket += pnl              # 100% 인출
    working_capital = INITIAL ($50) # 마진 항상 $50 유지
else:
    working_capital += pnl
    if working_capital < 0:
        deficit = -working_capital
        if safe_pocket >= deficit:
            safe_pocket -= deficit  # safe에서 보충
        working_capital = 0
```

### V0의 직관적 설명
- **마진은 항상 $50 고정** (한 트레이드당 최대 손실 제한)
- **이익 100% safe pocket으로** (절대 잃지 않는 돈 누적)
- **손실은 working에서만** (safe 건드리지 않음)
- 결과: ruin 4.8%, 3년 후 평균 +$353 (자본 8배)

### 사용자 의도와의 차이
| | 사용자 제안 (60% reinvest) | 검증된 정답 (V0 = 100% 인출) |
|---|---|---|
| 벌면 | 60% 재투자, 40% safe | **0% 재투자, 100% safe** |
| 마진 | 동적 증가 | $50 고정 |
| 이론 근거 | 복리 (compound) | 부분 켈리 + Kelly Bankroll |
| 청산 시 | working 전부 0 → 게임 끝 | 마진 한도 내, 다시 시도 가능 |
| MC ruin | 59.3% | **4.8%** |
| 잭팟 (p99) | $8,891 (자본 178배) | $897 |

---

## 3. 전략 종합 — 4-tier 추천

| Tier | base 전략 | 자본 정책 | $50 → 평균 | ruin | 비고 |
|---|---|---|---:|---:|---|
| **🛡 안전 최강** | **vol_expansion + L4 NoSL** | **V0 (100% 인출)** | **$403 (3년)** | **4.8%** ✅ | **사용자 의도 정답** |
| 균형 | vol_expansion + L3 (SL-70/TP+1000) | V0 | $389 (3년) | 11.5% | 잭팟 가능성 약간 ↑ |
| 잭팟 시도 | squeeze_release + L1 (SL-90/TP+1000) | V0 | $169 (3년) | 42.2% | 11배 한 방 가능 |
| 풀 켈리 도박 | vol_expansion + L4 + V1 60% reinvest | 60% 재투자 | $34 (3년) | 59.3% | p99 = $8891 (1% 확률) |

---

## 4. 실시간 Paper Trading Bot

### 실행 상태
- **PID**: 63285 (background, nohup)
- **시작**: 2026-04-26 04:22 UTC
- **전략**: vol_expansion + L4 + V0 ← **검증된 최적**
- **레버리지**: 10x
- **마진**: $50 고정 (V0)
- **유니버스**: PEPE/USDT, WIF/USDT, DOGE/USDT
- **폴링**: 60초

### 모니터링 명령어

```bash
# 실시간 상태 확인 (working/safe pocket, trade count)
cat /Users/tttksj/first_repo/quant_runtime/paper_bot_state.json | python3 -m json.tool

# 이벤트 로그 (entry/exit/error 모두)
tail -f /Users/tttksj/first_repo/quant_runtime/paper_bot_log.jsonl

# stdout 로그 (콘솔 출력 그대로)
tail -f /Users/tttksj/first_repo/quant_runtime/paper_bot_stdout.log

# 봇 살아있는지 확인
ps -p $(cat /Users/tttksj/first_repo/quant_runtime/paper_bot.pid)

# 봇 정지 (state는 보존됨)
kill -INT $(cat /Users/tttksj/first_repo/quant_runtime/paper_bot.pid)

# 봇 재시작 (이전 state 이어받음)
cd /Users/tttksj/first_repo && nohup python3 scripts/quant_phase23_paper_bot.py > quant_runtime/paper_bot_stdout.log 2>&1 &
echo $! > quant_runtime/paper_bot.pid

# 현재 시장에서 신호 즉시 평가 (one-shot)
python3 /Users/tttksj/first_repo/scripts/quant_phase23_check_now.py
```

### Bot 내부 동작 (검증완료)
1. 60초마다 Bitget perp 1h kline fetch (PEPE/WIF/DOGE)
2. vol_expansion 신호 평가:
   - `bb_width_rank ≥ 0.7` (BB 폭이 100bar 중 상위 30%)
   - `mom24 > 3%` (24h 모멘텀 양)
   - `close > bb_upper` (BB 상단 돌파)
   - `vol_r ≥ 1.5` (거래량 1.5배 폭증)
3. 시그널 발화 시 → virtual position OPEN ($50 margin × 10x = $500 notional)
4. 매 60초마다 exit 조건 체크:
   - **TP**: ROE +500% (가격 +50%) 도달
   - **Signal off + profit**: vol_expansion 종료시 ROE > 0이면 익절
   - **Liquidation**: ROE -95% (가격 -9.5%) → -$50 (margin 전소)
5. 종료 시:
   - 이익 → 100% safe_pocket으로 (working은 $50 유지)
   - 손실 → working에서 차감 (필요시 safe에서 보충)
6. 매 이벤트 → state.json 업데이트, log.jsonl 추가

### 예상 동작 (백테스트 기반)
- 1년 24회 trade 발생 (월 2회)
- 79% 이김 (signal_off in profit ROE 평균 +50%)
- 큰 한 방 (TP +500% = +$248) 1년에 1-2회
- 청산 1년에 2-3회 (-$50씩)
- 평균 +$117/년 → safe pocket 누적

---

## 5. 1주 후 / 1달 후 비교 체크포인트

### 검증할 것
1. **신호 빈도**: 백테스트 24회/년 = 약 2회/월 → 1달에 시그널 1-3회 떠야 정상
2. **승률**: 백테스트 79% → 첫 5건 중 3-4건 이겨야 정상
3. **safe pocket 누적 속도**: 1달 +$10 정도 예상 ($117/년 / 12)
4. **청산 빈도**: 1달에 0-1회 정상 (10% 청산률)

### 만약 결과가 백테스트와 어긋나면
- 신호 빈도가 절반 이하 → market regime 변화 (trending 시장 부재)
- 승률 50% 이하 → entry filter 조정 필요 (mom24 임계값 ↑)
- 청산률 30%+ → 메메즈 변동성 증가, leverage 5x로 낮추기 검토

---

## 6. 산출 파일

```
scripts/
  quant_phase22_partial_reinvest.py  ← 부분 재투자 백테스트
  quant_phase23_paper_bot.py         ← 실시간 paper bot
  quant_phase23_check_now.py         ← 즉시 신호 평가 도구

quant_runtime/
  paper_bot_state.json     ← 봇 현재 상태 (working/safe/trades)
  paper_bot_log.jsonl      ← 모든 이벤트 (OPEN/CLOSE/error)
  paper_bot_stdout.log     ← 콘솔 출력
  paper_bot.pid            ← 프로세스 ID

quant_runtime/master_engine_runs/
  phase22_partial_reinvest.json       ← 30 backtest results raw
  PARTIAL_REINVEST_FINAL.md           ← 이 문서
```

---

## 7. 한 줄 결론

> **"60% 재투자 + 40% safe"는 직관적으로 좋아 보이지만 백테스트로 보면 청산 한 번에 끝남 (ruin 59%).**
> **진짜 정답은 "0% 재투자 + 100% safe (V0)"** — 마진 $50 고정, 이익은 모두 safe pocket으로.
> **MC ruin 4.8%, 3년 후 평균 +$353. 청산 한 번 맞아도 -$50 한정**.
>
> Paper bot이 이 검증된 V0 + vol_expansion + L4 정책으로 PID 63285에서 실시간 작동 중. 1주~1달 모니터링 후 백테스트 예측치(승률 79%, 월 +$10 safe 누적)와 비교하면 진짜 검증 끝납니다.
