# Strategy Registry — quant_binance

> 단일 마스터 인덱스. 모든 전략(=파라미터 세트)을 ID·상태·핵심 가설·최신 성과 한 줄씩.
> **전략은 `overrides.json` 한 파일로 정의됨**. 코드 변경 없이 `STRATEGY_OVERRIDE_PATH=strategies/<ID>/overrides.json` 으로 갈아끼움.

## 사용 규칙 (반드시 지킬 것)

1. **새 전략 만들기**: `/strategy-new <ID> --base <prev_ID>` (또는 직접 `_template/` 복사)
2. **전략 평가**: `/strategy-eval <ID>` (백테스트 + 페이퍼라이브 자동 + card.md 결과 갱신 + 이 표 갱신)
3. **변수 1개 룰**: 새 전략은 직전 전략 대비 **단일 변수만** 변경. 다중 변수 변경 = 함정. 다중 변경이 필요하면 별도 ID 2개로 분리.
4. **Status 라벨**:
   - `live` — 실제 자본 배정 중
   - `paper` — 페이퍼 라이브 검증 중
   - `bt-only` — 백테스트만 통과, 라이브 미투입
   - `shelved` — 일시 보관 (다시 쓸 수도)
   - `dead` — 명백히 폐기. 가설·결론은 후속 전략에 상속됨

## 전략 비교 표

> 비고: `replay` 모드는 진입 의사결정만 평가 (PnL/승률/MDD/Sharpe N/A). closed-trade 메트릭 = `batch_backtest.py` (klines) 또는 페이퍼라이브 누적.

| ID | 가설 한 줄 | Status | 부모 | 변경 변수 | 거래 | 진입률 | Gross bps | Net bps | 승률 | Live PnL | 결론·다음 후보 |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| [S001](S001_baseline/card.md) | 현 기본 config 그대로 — 베이스라인 측정 | bt-only | — | (베이스) | 1,258 | 70% | **−1.16** | −17.16 | 35.9% | — | **신호 random 수준 + cost 못 이김. 진입 늘리기·레버리지 ↑ 모두 금지. 다음 후보: Universe=BTC 단독(S002), Cost 절감(S003), Holding 늘리기(S004)** |

## 사고 사이클 (반복할 것)

```
1. 가설 1줄 (정량 예측 포함)
   예: "거래량 필터 1.5x → 1.2x 완화 시 진입 빈도 3배, 승률 5%p↓ 예상"
2. 변수 1개만 변경 → 새 ID 발급 (S002 등)
3. /strategy-eval <ID>  →  백테스트 + 페이퍼 동시 평가, 결과 자동 기록
4. card.md 의 "결론" 섹션에 한 줄 누적
5. 결론 위에서 다음 가설 → 다음 ID
```

**규칙 어김 = 학습 누적 안 됨**. 같은 전략을 다른 이름으로 짓거나 (변수 여러 개 동시 변경) 같은 함정 반복.

## 참고

- **자본 컨텍스트**: $50 자본 + 도박성 OK + 거래당 큰 수익 추구.  
  → 진입 빈도 ≥ 3건/일, 거래당 expectancy +0.5R↑, 5~10x 레버리지, 롱·숏 양방향 권장 (CLAUDE.md "처방 A" 참조).
- **베이스라인 (S001)** 은 변경 금지. 측정 기준선 역할.
- **runs/ 폴더**: 각 전략의 평가 결과 요약 JSON 누적. 원본 raw 트레이스(`decisions.jsonl` 등)는 `quant_runtime/` 또는 `iCloudDrive/quant_archive/quant_runtime/` 에 별도 보관.
