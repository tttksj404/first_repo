# Multi-Arm Cross-Coin Gate Experiment — Final Decision

## Verdict: **Keep production A_live (gate=ON, full 6-symbol universe)**

## Evidence

### Live paper run (2026-04-26 00:43 KST → 07:50 KST, 7h)
- Market regime quiet (low volatility) → all 4 arms produced 0 trades / 0 blocks / 0 boosts
- Top rejection: `SYMBOL_PROFILE_EXPECTED_PROFIT_TOO_SMALL` (68.6% of A_live's 3234 decisions)
- Live paper experiment INSUFFICIENT to compare arms in this regime

### Offline replay (cycle-level synthetic entries, 4-day in-sample)
Replayed 187 cycles × 6 symbols against the cross-coin EV table for each arm config:

| Arm | Univ | Gate | Entries | Blocked | Boosted | Win Rate | Net$/trade |
|---|---|---|---|---|---|---|---|
| D_alts | 4 | ON | 656 | 44 | 0 | **43.1%** | **-$0.0155** |
| A_live (production) | 6 | ON | 876 | 174 | 42 | 39.6% | -$0.0171 |
| C_majors | 3 | ON | 459 | 66 | 11 | 35.7% | -$0.0205 |
| B_gate_off | 6 | OFF | 1050 | 0 | 0 | 39.1% | -$0.0206 |

Source: `scripts/quant_replay_arms_offline.py` → `quant_runtime/multi_arm_replay_summary.json`

### Validated facts
1. **Gate works**: A vs B (identical universe) shows gate blocks 174 negative-EV entries → -$6.66 less loss (-30.7%)
2. **Gate's value is alt-dominated**: 4/5 EV-table blockers are alt scenarios (PEPE/DOGE). Gate barely helps majors-only arm.
3. **D_alts looks best per-trade** but is in-sample (EV table training set was alts-heavy)

### Why keep A_live not switch to D_alts
- D_alts win comes partly from in-sample bias (gate trained on this exact window)
- A_live's 6-symbol diversity reduces concentration risk
- Production stability > marginal per-trade edge on synthetic backtest

## Follow-up actions

1. **Wait 7+ days for fresh out-of-sample data**, then run `scripts/quant_paper50_cross_coin_ev_retrain.py` to refresh EV table. Compare retrained candidates vs current scenarios → only promote if winrate AND ev_bps both stable across windows.
2. **Re-run `scripts/quant_replay_arms_offline.py`** on the post-retrain window to verify gate still adds 20%+ loss-reduction vs gate-off.
3. **If D_alts persists as winner** in fresh OOS replay, consider weighting via `priority_symbols` rather than full universe restriction (preserves majors as fallback).
4. **Monitor live A_live**: track `cross_coin_blocked` and `cross_coin_size_boosted` counters in `forensics/decisions.jsonl` weekly. If 0 for 7+ consecutive days, regime has shifted and EV table needs retrain.

## Files generated
- `quant_runtime/multi_arm_final_report.txt` (live paper, 0 entries)
- `quant_runtime/multi_arm_replay_summary.json` (offline replay)
- `quant_runtime_arm{A,B,C,D}_replay/forensics/decisions.jsonl` + `closed_trades.jsonl`
- `scripts/quant_replay_arms_offline.py` (replay tool)
