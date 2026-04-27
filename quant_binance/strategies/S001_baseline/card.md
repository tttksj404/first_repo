# S001 — Baseline (현 기본 config)

- **Status**: bt-only
- **부모**: —
- **변경 변수 (vs 부모)**: (베이스라인 — 변경 변수 없음)
- **TF / Symbol**: 5m, 15m / 현 universe (CLI `--universe` 또는 `UNIVERSE_SYMBOLS` 기준)
- **레버리지**: 기본값 (settings.py 의 LeverageConfig)
- **방향**: 현 config 그대로 (대체로 롱 위주)

## 가설 (정량 예측 포함)

> 베이스라인이므로 가설 없음. **모든 후속 전략의 비교 기준선**.

## 진입 룰

> `quant_binance/strategy/regime.py` + `config.example.json` 기본값.
> 핵심:
> - `compute_predictability_score()` 가 임계값 이상
> - `passes_cost_gate()` 통과
> - 각 코인별 `coin_profiles.py` 게이트 통과
> - 매크로/펀딩 오버레이 게이트 통과 (활성 시)

## 청산 룰

> `policy/execution.py` + `risk/` 의 기본 룰.
> TP/SL/트레일/시간정지는 config 의 `execution.exit_*` 그룹 참조.

## 백테스트 결과

> `/strategy-eval S001` 실행 시 자동 갱신. 첫 실행 전이면 비어 있음.

| 기간 | 거래 | 승률 | 평균R | MDD | Sharpe | 결과 파일 |
|---|---:|---:|---:|---:|---:|---|
| (미실행) | — | — | — | — | — | — |

## 페이퍼·실거래 결과

| 기간 | 모드 | 거래 | 승률 | PnL | 평균 슬리피지 | 결과 파일 |
|---|---|---:|---:|---:|---:|---|
| (미실행) | — | — | — | — | — | — |

## 결론 (다음 전략에 상속할 지식)

> 첫 평가 후 작성. 베이스라인의 expectancy/거래빈도/실패 패턴이 모든 후속 전략의 출발점.

- 가설 적중 여부: (베이스라인이므로 없음)
- 의외 발견: (실측 후 작성)
- 다음 후보 (변수 1개): **사용자 판단 — CLAUDE.md 처방 A 의 "$50 자본·고변동성" 방향이라면 거래 빈도를 높이는 단일 변수부터** (예: cost_gate 임계값 완화, 거래량 필터 완화, universe 확장)

## 변경 이력

| 일자 | 변경 | 사유 |
|---|---|---|
| 2026-04-27 | 초기 작성 (Strategy Registry 도입) | 전략 카탈로그 시스템 시작점 |
