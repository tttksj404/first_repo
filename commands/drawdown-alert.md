# /drawdown-alert — 드로다운 모니터링 + 회로차단기

실시간 드로다운을 추적하고 임계치 초과 시 봇을 자동으로 정지시키는 로직을 설계합니다.

## 사용법

```
/drawdown-alert                  # 현재 드로다운 상태 확인
/drawdown-alert config           # 임계치 설정 가이드
/drawdown-alert recovery         # 회복 예상 시간 계산
/drawdown-alert history          # 드로다운 이력 분석
```

## 회로차단기 설정 (권장값)

```python
CIRCUIT_BREAKER = {
    "daily_loss_limit"    : -0.05,   # 일일 -5% → 당일 거래 중단
    "weekly_loss_limit"   : -0.10,   # 주간 -10% → 파라미터 재검토
    "max_drawdown_limit"  : -0.20,   # -20% → 봇 완전 정지
    "consecutive_losses"  : 5,       # 연속 5패 → 포지션 크기 절반
    "recovery_mode_below" : -0.10,   # -10% 이하 → 포지션 크기 50% 감소
}
```

## 구현 코드 템플릿

```python
class DrawdownGuard:
    def __init__(self, peak_balance: float):
        self.peak = peak_balance
        self.daily_start = peak_balance

    def check(self, current_balance: float) -> str:
        drawdown = (current_balance - self.peak) / self.peak
        daily_dd = (current_balance - self.daily_start) / self.daily_start

        if daily_dd <= -0.05:
            return "DAILY_STOP"      # 오늘 거래 종료
        if drawdown <= -0.10:
            return "HALF_SIZE"       # 포지션 크기 50%
        if drawdown <= -0.20:
            return "FULL_STOP"       # 봇 정지 + 알림
        return "NORMAL"
```

## 드로다운 회복 분석

```
회복 필요 수익률 계산:
  -10% 드로다운 → +11.1% 필요
  -20% 드로다운 → +25.0% 필요
  -30% 드로다운 → +42.9% 필요
  -50% 드로다운 → +100.0% 필요

예상 회복 기간 (승률·수익비 기준):
  승률 55%, 평균 R:R 1:1.5 기준
  -10% 드로다운 → 약 18거래일 예상
```

## 출력 형식

```
DRAWDOWN STATUS — 2026-03-27 14:30
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
최고 잔고      : $10,000
현재 잔고      : $8,950
현재 드로다운  : -10.5% 🟡
일일 드로다운  : -2.1% ✅
연속 손실      : 3회 ✅

회로차단기 상태:
  일일 한도 (-5%)  : ✅ 여유
  주간 한도 (-10%) : ⚠️ 임박
  전체 한도 (-20%) : ✅ 여유

포지션 크기 모드: HALF_SIZE (50% 감소 적용 중)
예상 회복 기간  : 약 14거래일
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
권고: 포지션 크기 유지, 주간 한도 모니터링 강화
```
