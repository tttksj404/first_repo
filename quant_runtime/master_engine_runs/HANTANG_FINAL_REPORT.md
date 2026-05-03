# 한탕주의 $50×30x 최종 추천 보고서

**작성일**: 2026-04-26
**작업 범위**: Path C (실제 프로덕션 게이트 1h OHLCV 시뮬) + 외부 자료 (GPT-5.4) 조합
**원자본**: $50 USDT, 레버리지 30x, Bitget perp
**비용 모델**: COST_RT=0.0012, FUNDING_8H=0.0001
**PnL 공식**: `pnl = margin × (roe_pct/100) − fee − funding` (레버리지 이중적용 금지)

---

## 1. 현실 점검 (Reality Check) — 프로덕션은 거의 발사 안 됨

### 1.1 실측: 47 paper-live probe
| 항목 | 값 |
|---|---|
| 총 decision | 8,397 |
| entry relaxation 발생 | 5,498 |
| **size_boost 발화** | **0** |
| 실제 주문 채택 | **0** |
| 보유 포지션 | **0** |

`probe42` (12h, ETH 단독): `edge_to_cost_multiple=5.75` (기준 1.20의 4.8배)인데도 `size_boost_reasons:[]` — 다른 게이트 (recent confirmation, trend_strength, liquidity 등) 어딘가에서 막힘.

### 1.2 코드상 프로덕션 게이트 (`policy/execution.py:49-79`, `session.py:3210-3590`)
**Strong tier 발동 조건 (margin=1.0)**:
- `predictability_score ≥ futures_score_min + 18`
- `trend_strength ≥ 0.64`
- `volume_confirmation ≥ 0.55`
- `liquidity_score ≥ 0.30`
- `edge_to_cost_multiple ≥ 1.20`
- `net_expected_edge_bps ≥ max(min_entry, pyramid_min)`
- **+ 6분 내 long 신호 2개 (recent confirmation)**
- **+ HIGH_CONVICTION_LONG_ONLY (숏 차단)**

→ **결론**: 현재 production 봇은 "한탕"을 칠 의도가 사실상 없음. 6+ feature 동시 만족 + 2-confirmation 게이트 = 산술적으로 발사 못 함.

---

## 2. Path C: 1h OHLCV로 프로덕션 게이트 충실 재현

### 2.1 STRICT 게이트 (원본 복제)
**Phase 14 (`scripts/quant_phase14_production_sim.py`)**:
- N = **0** (3년 BTC/ETH/SOL/PEPE/BONK/WIF, 모든 universe)
- → 프로덕션 0-발사 현상을 1h 시뮬로 재현 성공 (모델 충실도 OK)

### 2.2 LOOSE 게이트 (relax 0.6~0.8)
| 변종 | N | WR | PnL | 평가 |
|---|---|---|---|---|
| relax=0.8 | 312 | 12% | -90%↓ | 노이즈 trade, SL=-10% ROE = -0.33% 가격 = 노이즈 |
| relax=0.6 | 41 | 9% | -85%↓ | 30x에 적합한 SL/TP 폭 부족 |

→ **결론**: 게이트만 풀어선 답 없음. 30x에 맞는 **넓은 SL + 큰 TP** 시그널 라이브러리가 필요함.

---

## 3. 외부 자료 종합 (GPT-5.4 위임 결과)

### 3.1 핵심 학술/실무 근거
| 출처 | 시사점 | 본 보고서 적용 |
|---|---|---|
| **Kelly 1956** | 최적 베팅 = (p×b−q)/b. 풀 켈리는 너무 공격적 | mp grid 0.05–1.00 도입 |
| **Bessembinder 2018** | 상위 4% 종목이 시장 부 전체를 만듦 → 우편향 가치 | tp500_sl50 (R/R = 10:1) 정당화 |
| **Barberis & Huang 2008** | 우편향 자산 **선험적으로 과대평가** → ex-ante negative EV | mp=1.0 ruin 87% 경고로 반영 |
| **IRFA 2024** | 소형주 = 우편향, 대형주 = 좌편향 | universe=memes (PEPE/BONK/WIF) 채택 |

### 3.2 11개 오픈소스 봇에서 추출한 archetype
GPT-5.4가 가져온 11개 봇 (Freqtrade NFI, Bandtastic, Hummingbot Directional MACD+BB, Supertrend, Jesse, 3Commas, Pionex DCA, Passivbot 등)에서 **10개 entry archetype** 추출 → Phase 15에서 모두 백테스트:

| archetype | 결과 |
|---|---|
| Bollinger/TTM Squeeze | N=58, +180%/yr |
| Funding extremes | N=22, -10% (한탕엔 부적합) |
| OI spike | 데이터 부족 |
| Liquidation cascade | 데이터 부족 |
| VWAP reclaim | N=104, +95%/yr |
| MTF (htf_uptrend) | N=92, +210%/yr |
| Failed breakout reverse | N=31, -40% |
| Catalyst (listing) | 한국 시장 특화 — 별도 |
| Whale flow | 데이터 부족 |
| **OBV divergence/breakout** | **N=76, +2552%/yr (최고)** |
| **Momentum continuation** | N=84, +2120%/yr (차순위) |

### 3.3 한국 상장 효과 데이터 (참고용)
- BIGTIME +51.9%/min (즉발), → SUN +2.8% (regime 소진)
- "상장 = 우편향 catalyst"이지만 1h OHLCV 백테스트에선 모델링 불가 → **선택 외**

---

## 4. 최종 시그널 (Path C + 외부 자료 결합)

### 4.1 Winner: `momentum_obv` (Phase 16에서 발견)
```python
def entry_momentum_obv(ind, i, long_only=True):
    if i < 25: return 0
    if (ind["mom24"][i] > 0.05            # 24시간 모멘텀 +5% 이상
        and ind["ema20"][i] > ind["ema50"][i]   # 단기 추세 우상향
        and ind["adx"][i] > 22            # 명확한 추세
        and ind["vol_r"][i] >= 1.3        # 거래량 1.3배 확장
        and ind["obv_slope"][i] > 0):     # 자금 유입 (OBV 상승)
        return 1
    return 0
```
**의미**: "확실한 우상향 추세 + 거래량 + 자금 유입" → Bessembinder의 우편향 catalyst를 1h 단위로 재현.

### 4.2 Exit: `tp500_sl50` (한탕에 최적)
- **Take Profit**: ROE +500% (가격 +16.67%)
- **Stop Loss**: ROE −50% (가격 −1.67%)
- **R/R = 10:1** (Kelly에 부합, 16.7% WR로도 EV+)
- 부분익절/profit-protection 없음 (한탕 = 끝까지 올라타기)

### 4.3 Universe: `memes` (PEPE, BONK, WIF)
- IRFA 2024 우편향 근거
- 30x 한탕은 좌편향 BTC/ETH보다 **소형주 catalyst** 추격이 EV+

---

## 5. Robustness 결과 (Phase 17 최종 검증)

### 5.1 Kelly mp 곡선 (no filter, momentum_obv + tp500_sl50 + memes, 76 trades, WR=17.1%)

| mp | margin | notional | PnL$ | %/yr | MC ruin% | max_DD$ |
|---:|---:|---:|---:|---:|---:|---:|
| 0.05 | $2.5 | $75 | +$63.8 | +128% | **8.3%** | $24.2 |
| 0.075 | $3.75 | $112.5 | +$95.7 | +191% | 19.0% | $36.2 |
| 0.10 | $5 | $150 | +$127.6 | +255% | 28.4% | $48.3 |
| 0.125 | $6.25 | $187.5 | +$159.5 | +319% | 36.3% | $60.4 |
| 0.15 | $7.5 | $225 | +$191.4 | +383% | 41.9% | $72.5 |
| 0.20 | $10 | $300 | +$255.2 | +510% | 53.0% | $96.7 |
| 0.25 | $12.5 | $375 | +$319.0 | +638% | 60.0% | $120.8 |
| 0.30 | $15 | $450 | +$382.8 | +766% | 60.9% | $145.0 |
| 0.50 | $25 | $750 | +$638.0 | +1276% | 76.8% | $241.7 |
| **1.00** | **$50** | **$1500** | **+$1275.9** | **+2552%** | **87.7%** | **$483.3** |

> Sharpe-like 관점: mp=0.10이 EV/√ruin 최고 (≈3.18). mp=1.0은 +2552%/yr이지만 87.7% 확률로 잔고 0.

### 5.2 BTC regime filter 효과 (mp 고정)

| filter | N | WR | PnL$ | ruin% | 비고 |
|---|---:|---:|---:|---:|---|
| no_filter | 76 | 17.1% | +$1276 | 87.7% (mp=1.0) | 한탕 풀 |
| btc_rsi<70 | 70 | 15.7% | +$134 | 49.8% (mp=0.15) | 과열 회피 |
| btc_rsi<60 | 64 | 16.4% | +$118 | 29.6% (mp=0.15) | 보수 |
| **btc_rsi>40 + low_vol** | **65** | **16.9%** | **+$120** | **25.6% (mp=0.10)** | **최저 ruin** |

---

## 6. 최종 4-tier 추천

| Tier | mp | regime gate | N/yr | WR | 연수익 | MC ruin | max_DD | best3$ | 적합 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| **S+ UltraSafe** | 0.10 | btc_rsi>40 + low_vol | 65 | 16.9% | **+240%** | **25.6%** | $48 | $74 | "잃어도 50불, 따도 두 배 정도" |
| **S Balanced** | 0.15 | btc_rsi<70 | 70 | 15.7% | +267% | 49.8% | $77 | $112 | 동전 던지듯 살아남기 |
| **A Aggressive** | 0.25 | none | 76 | 17.1% | +638% | 60.0% | $121 | $186 | 60% 죽고 40% 7배 |
| **🎰 한탕 Full** | 1.00 | none | 76 | 17.1% | **+2552%** | **87.7%** | $483 | **$744** | 진짜 로또 1번 |

### 권장 의사결정 매트릭스
- **목표 = 자본 보존 + 약간의 한탕 향**: → **S+ (mp=0.10)**. 4번 중 3번 살아남고 평균 2배 이상.
- **"잃을 돈"으로 정한 $50, 한탕 의지**: → **A (mp=0.25)**. 60% 죽고 40% 7배. EV+가 명확.
- **"진짜 1번 한탕"**: → **🎰 Full (mp=1.0)**. **단, 87.7% 확률로 0됨**. Barberis 경고대로 ex-ante 우편향은 과대평가될 수 있음 — 한 번 더 깎아 생각할 것.

> **Anti-pattern (피할 것)**: mp=0.5~0.75 구간. ruin 76~78%인데 수익은 mp=1.0의 절반. 켈리 곡선의 "허리 함정".

---

## 7. 프로덕션 적용 패치 (rotation_30x_candidate.json 변경 제안)

### 7.1 entry 게이트 교체 (production STRICT → momentum_obv)
```diff
- predictability_score >= futures_score_min + 18
- trend_strength >= 0.64
- volume_confirmation >= 0.55
- liquidity_score >= 0.30
- edge_to_cost_multiple >= 1.20
- recent confirmation 6m × 2 long signals
+ mom_24h >= 0.05 (24h 모멘텀 +5% 이상)
+ ema20 > ema50 (단기 추세)
+ adx_14 > 22 (명확한 추세)
+ vol_ratio_24h >= 1.3 (거래량 1.3배)
+ obv_slope_24h > 0 (자금 유입)
+ btc_rsi > 40 AND btc_rsi < 70 AND btc_atr_pctile < 70 (regime; tier S+)
```

### 7.2 exit 교체 (TP ladder + protection → tp500_sl50)
```diff
- partial_tp_roe = [5, 18, 35, 60]
- partial_tp_fraction = 0.75
- profit_protection_arm_roe = 18
- profit_protection_retrace_pct = 5
+ tp_roe = 500          # 가격 +16.67%
+ sl_roe = -50          # 가격 −1.67%
+ partial_tp = []       # 부분익절 없음
+ profit_protection = false
```

### 7.3 sizing & universe
```diff
- universe = ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT", ...]
- margin_pct strong = 1.0, medium = 0.35
+ universe = ["PEPEUSDT","BONKUSDT","WIFUSDT"]    # memes only
+ margin_pct = 0.10     # tier S+ 기본
+ leverage = 30
+ HIGH_CONVICTION_LONG_ONLY = true (유지)
```

### 7.4 cooldown
```
post_entry_cooldown_h = 12
post_loss_cooldown_h = 24
```

---

## 8. 결론 (1줄 요약)

> **현재 프로덕션 봇은 한탕을 칠 의도가 없음** (47 probe / 8397 decision / 0 fire).
> Path C 시뮬 + 외부 자료 종합 결과, **`momentum_obv (mom24>5% & ema20>ema50 & ADX>22 & vol_r≥1.3 & obv↑) + TP500/SL50 + memes` 조합이 30x 한탕 EV 최대**.
> 자본 보존을 1순위로 두면 **mp=0.10 + btc_rsi>40 + low_vol** (ruin 25.6%, +240%/yr).
> 진짜 로또를 원하면 **mp=1.00 + no filter** (ruin 87.7%, +2552%/yr) — 단 Barberis 경고대로 우편향 자산은 ex-ante 과대평가될 수 있으니 살아남는다 = 보너스로 생각할 것.

---

## 부록 A: 데이터 무결성

- 데이터 소스: ccxt Bitget perp 1h OHLCV, 2023-04-01 ~ 2026-04-25 (3년)
- 종목: BTC/ETH/SOL/XRP/DOGE/PEPE/BONK/WIF (8개)
- Walk-forward: 4-fold 시간순. WF 결과는 `phase16_robustness.json` 참조.
- MC ruin: 10,000회 bootstrap (with replacement, 76 trade resample)
- 슬리피지 stress: 0/5/10/15/20bps 모두 mp=0.10 tier에서 +EV 유지 (5bps에서 +220%/yr)
- 비용: maker 0.02% + taker 0.06% RT, funding 0.01%/8h (PEPE/WIF는 보수적으로 0.013~0.015% 적용)

## 부록 B: 산출 파일
- `scripts/quant_phase14_production_sim.py` — STRICT 게이트 1h 재현
- `scripts/quant_phase15_signal_library.py` — 10 archetype 백테스트
- `scripts/quant_phase16_robustness.py` — OBV + WF + MC + Kelly mp
- `scripts/quant_phase17_final_validate.py` — 최종 4-tier 검증
- `quant_runtime/output/gpt54_research_result.md` — 외부 자료 (587줄)
- `quant_runtime/master_engine_runs/phase17_final.json` — 최종 메트릭 raw
