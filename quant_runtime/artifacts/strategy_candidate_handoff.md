# Strategy Candidate Handoff

## Rotation Candidates
- `majors` lookback=168h rebalance=24h top_k=1 score=return positive=True ema=True return=+201.98% PF=1.06 MDD=45.33% Sharpe=1.43
- `majors` lookback=168h rebalance=24h top_k=1 score=return_over_vol positive=True ema=True return=+100.79% PF=1.06 MDD=50.53% Sharpe=1.25

## Carry / Basis Candidates
- `SOLUSDT` funding>=0.00015 basis>=5.0bps hold=8h stop=100 tp=160 n=7 PF=6.46 WF=4/4 stress24=+552.9bps
- `SOLUSDT` funding>=0.00010 basis>=5.0bps hold=24h stop=100 tp=160 n=18 PF=1.61 WF=3/4 stress24=+373.7bps
- `SOLUSDT` funding>=0.00015 basis>=5.0bps hold=16h stop=100 tp=160 n=7 PF=3.23 WF=4/4 stress24=+434.1bps
- `SOLUSDT` funding>=0.00015 basis>=5.0bps hold=24h stop=100 tp=160 n=7 PF=3.23 WF=4/4 stress24=+434.1bps
- `SOLUSDT` funding>=0.00010 basis>=5.0bps hold=16h stop=100 tp=160 n=18 PF=1.50 WF=3/4 stress24=+277.7bps

## Suggested Next Commands
- `python3 scripts/rotation_strategy_scan.py --workers 4`
- `python3 scripts/rotation_strategy_shortlist.py`
- `python3 scripts/carry_basis_strategy_scan.py`
- `python3 scripts/strategy_candidate_handoff.py`
