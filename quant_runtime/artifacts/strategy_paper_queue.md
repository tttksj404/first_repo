# Strategy Paper Queue

## Priority 1: carry — SOLUSDT funding>=0.00015 basis>=5.0bps hold=8h stop=100 tp=160
- Goal: carry/basis 가설을 최근 구간과 paper shell 감시 대상으로 우선 검증
- Command: `python3 scripts/carry_basis_strategy_scan.py`
- Command: `UNIVERSE_SYMBOLS=SOLUSDT sh scripts/quant_paper_live_shell.sh quant_binance/examples/paper_live_fixture.sample.json quant_runtime/output/paper-live-shell/latest/summary.json`
- Command: `sh scripts/quant_report.sh quant_runtime`
- Notes: `{"symbol": "SOLUSDT", "funding_threshold": 0.00015, "basis_threshold_bps": 5.0, "hold_hours": 8, "positive_folds": 4, "stressed_total_return_bps": 552.94}`

## Priority 2: rotation — majors lookback=168h rebalance=24h top_k=1 score=return pos=True ema=True
- Goal: recent-comparison 재검증 후 majors 전용 paper 모니터링 여부 판단
- Command: `python3 scripts/rotation_strategy_scan.py --workers 4`
- Command: `python3 scripts/rotation_strategy_shortlist.py`
- Command: `python3 scripts/strategy_candidate_ranker.py`
- Notes: `{"lookback_hours": 168, "rebalance_hours": 24, "top_k": 1, "score_mode": "return", "max_drawdown_pct": 45.3305}`

## Priority 3: carry — SOLUSDT funding>=0.00015 basis>=5.0bps hold=16h stop=100 tp=160
- Goal: carry/basis 가설을 최근 구간과 paper shell 감시 대상으로 우선 검증
- Command: `python3 scripts/carry_basis_strategy_scan.py`
- Command: `UNIVERSE_SYMBOLS=SOLUSDT sh scripts/quant_paper_live_shell.sh quant_binance/examples/paper_live_fixture.sample.json quant_runtime/output/paper-live-shell/latest/summary.json`
- Command: `sh scripts/quant_report.sh quant_runtime`
- Notes: `{"symbol": "SOLUSDT", "funding_threshold": 0.00015, "basis_threshold_bps": 5.0, "hold_hours": 16, "positive_folds": 4, "stressed_total_return_bps": 434.07}`

## Priority 4: carry — SOLUSDT funding>=0.00015 basis>=5.0bps hold=24h stop=100 tp=160
- Goal: carry/basis 가설을 최근 구간과 paper shell 감시 대상으로 우선 검증
- Command: `python3 scripts/carry_basis_strategy_scan.py`
- Command: `UNIVERSE_SYMBOLS=SOLUSDT sh scripts/quant_paper_live_shell.sh quant_binance/examples/paper_live_fixture.sample.json quant_runtime/output/paper-live-shell/latest/summary.json`
- Command: `sh scripts/quant_report.sh quant_runtime`
- Notes: `{"symbol": "SOLUSDT", "funding_threshold": 0.00015, "basis_threshold_bps": 5.0, "hold_hours": 24, "positive_folds": 4, "stressed_total_return_bps": 434.07}`

## Priority 5: carry — SOLUSDT funding>=0.00010 basis>=5.0bps hold=24h stop=100 tp=160
- Goal: carry/basis 가설을 최근 구간과 paper shell 감시 대상으로 우선 검증
- Command: `python3 scripts/carry_basis_strategy_scan.py`
- Command: `UNIVERSE_SYMBOLS=SOLUSDT sh scripts/quant_paper_live_shell.sh quant_binance/examples/paper_live_fixture.sample.json quant_runtime/output/paper-live-shell/latest/summary.json`
- Command: `sh scripts/quant_report.sh quant_runtime`
- Notes: `{"symbol": "SOLUSDT", "funding_threshold": 0.0001, "basis_threshold_bps": 5.0, "hold_hours": 24, "positive_folds": 3, "stressed_total_return_bps": 373.71}`

## Priority 6: carry — SOLUSDT funding>=0.00010 basis>=5.0bps hold=8h stop=100 tp=160
- Goal: carry/basis 가설을 최근 구간과 paper shell 감시 대상으로 우선 검증
- Command: `python3 scripts/carry_basis_strategy_scan.py`
- Command: `UNIVERSE_SYMBOLS=SOLUSDT sh scripts/quant_paper_live_shell.sh quant_binance/examples/paper_live_fixture.sample.json quant_runtime/output/paper-live-shell/latest/summary.json`
- Command: `sh scripts/quant_report.sh quant_runtime`
- Notes: `{"symbol": "SOLUSDT", "funding_threshold": 0.0001, "basis_threshold_bps": 5.0, "hold_hours": 8, "positive_folds": 4, "stressed_total_return_bps": 250.15}`
