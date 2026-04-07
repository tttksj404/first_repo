# /tearsheet — 표준 퍼포먼스 리포트 생성

트레이딩 성과를 전문적인 형식으로 정리합니다.
백테스트 결과 또는 실거래 이력에서 생성 가능.

## 사용법

```
/tearsheet                           # 전체 기간 리포트
/tearsheet --days 30                 # 최근 30일
/tearsheet --file trades.csv         # 파일에서 생성
/tearsheet --compare benchmark BTC   # BTC Buy&Hold 대비 비교
```

## 생성 항목

### 수익 요약
```
총 수익률      : +42.3%
연간 수익률    : +23.7% (CAGR)
BTC B&H 대비   : +8.4%p 초과 성과
최고 월        : 2025-11 (+12.1%)
최악 월        : 2025-08 (-6.3%)
```

### 리스크 지표
```
샤프 비율      : 1.67  (≥1.0 권장)
소르티노 비율  : 2.31  (≥1.5 권장)
칼마 비율      : 1.89  (연수익/MDD)
최대 드로다운  : -12.5%
드로다운 기간  : 18일 (2025-08-03 ~ 2025-08-21)
변동성(연)     : 14.2%
```

### 거래 통계
```
총 거래 수     : 412회
승률           : 61.4%
평균 수익 (win): +1.82%
평균 손실 (loss): -0.98%
수익 팩터      : 2.87
기대값(1회당)  : +0.63%
평균 보유시간  : 4.2시간
최대 연속 승   : 11회
최대 연속 패   : 6회
```

### 월별 수익률 히트맵
```
         Jan    Feb    Mar    Apr    May    Jun
2025    +3.2%  +5.1%  -1.3%  +8.7%  +2.9%  +4.4%
2026    +6.1%  -2.1%  +4.8%

         Jul    Aug    Sep    Oct    Nov    Dec
2025    +1.9%  -6.3%  +3.1%  +7.2% +12.1%  +5.6%
```

### 진입/청산 이유 분석
```
진입 신호별 성과:
  RSI 과매도        : 68% 승률 (87회)
  볼린저 하단 터치  : 54% 승률 (143회)
  MACD 골든크로스   : 59% 승률 (182회)

청산 이유별:
  TP 도달           : 55% (226회) → 평균 +1.82%
  SL 도달           : 30% (124회) → 평균 -0.98%
  시간 초과         : 15% (62회)  → 평균 +0.12%
```

## 구현 코드 (QuantStats 사용)

```python
import quantstats as qs

# trades DataFrame → returns Series로 변환
returns = trades.set_index('exit_time')['pnl_pct']

# 전체 리포트 HTML 생성
qs.reports.html(returns, output='tearsheet.html', title='Strategy Report')

# 핵심 지표만
qs.reports.metrics(returns, mode='full')

# BTC 대비 비교
btc = qs.utils.download_returns('BTC-USD')
qs.reports.full(returns, benchmark=btc)
```

## 출력 파일

```
reports/
  tearsheet_2026-03-27.html     # 전체 리포트 (브라우저로 열기)
  tearsheet_2026-03-27.pdf      # PDF 버전
  metrics_summary.txt           # 핵심 지표 텍스트
  monthly_returns.csv           # 월별 수익률 데이터
```
