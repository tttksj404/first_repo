# Strategy Execution Bundle

## Carry Overrides
- top1: `SOLUSDT funding>=0.00015 basis>=5.0bps hold=8h stop=100 tp=160` -> `/Users/tttksj/first_repo/quant_runtime/artifacts/candidate_overrides/strategy_override.carry_top1.json` score=183.68
- top2: `SOLUSDT funding>=0.00015 basis>=5.0bps hold=16h stop=100 tp=160` -> `/Users/tttksj/first_repo/quant_runtime/artifacts/candidate_overrides/strategy_override.carry_top2.json` score=121.19
- top3: `SOLUSDT funding>=0.00015 basis>=5.0bps hold=24h stop=100 tp=160` -> `/Users/tttksj/first_repo/quant_runtime/artifacts/candidate_overrides/strategy_override.carry_top3.json` score=121.19

## Rotation Review Bundles
- top1: `majors lookback=168h rebalance=24h top_k=1 score=return pos=True ema=True` -> `/Users/tttksj/first_repo/quant_runtime/artifacts/candidate_overrides/rotation_review_top1.json` score=51.84
- top2: `majors lookback=168h rebalance=24h top_k=1 score=return_over_vol pos=True ema=True` -> `/Users/tttksj/first_repo/quant_runtime/artifacts/candidate_overrides/rotation_review_top2.json` score=19.28
