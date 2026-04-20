# 30x Rotation Candidate Verification Report

Date: 2026-04-20 KST

Scope: sanitized verification summary for `strategy_override.rotation_30x_candidate.json`.

This report intentionally excludes raw runtime logs, account snapshots, request payloads, balances, image assets, and scraped external data. It keeps only the evidence needed to understand whether the strategy logic behaved as intended.

## Strategy Invariant

- Long-only turnaround baseline remains intact.
- Enter only high-conviction long candidates.
- Block fake longs when same-symbol recent short or weak/choppy signals are present.
- Re-open long entry only when the same symbol prints a clean post-short reversal sequence.
- Keep 30x sizing for qualified high-conviction entries instead of reducing exposure.
- Use paper/live-paper verification only; no live orders were intentionally placed during these checks.

## Implemented Guards

- Fast signal synchronization: 1-minute decision interval for the rotation candidate.
- High-conviction recent long confirmation gate.
- Fake-pump quality filters: trend, volume, liquidity, volatility, overheat, and edge-to-cost.
- Opposite-signal block: recent same-symbol futures short signals block high-conviction long entry.
- Clean-reversal unlock: after a recent short, long entry unlocks only after 3 clean same-symbol long confirmations.
- Long-only turnaround entry guard: raw short futures candidates are prepared as `cash:0`.
- Paper verification mode safeguards: simulated paper positions are not closed as missing on exchange.
- Live execution fail-closed hardening: leverage mismatch/rejection aborts entry, protection rejection triggers rollback.
- Guardian defaults restored: 60-second grace and unmanaged-only intervention.
- Funding bias fields added for candidate evaluation.

## Verification Evidence

### Automated Tests

- Full suite: `656 passed, 7 skipped`.
- Related regression subset after clean-reversal unlock: `271 passed`.
- Session regression suite after unlock: `175 passed`.
- Focused unlock tests: `3 passed`.

### Historical Fake-Long Replay

Source: `realtime_candidate_probe14_weak_fake_long_watch_30m` decision stream.

- ETH first long candidate after short cluster:
  - Recent ETH shorts within 6 minutes: 30.
  - Clean prior longs within 6 minutes: 0.
  - Result after patched guard: `cash/flat`.
  - Rejection: `HIGH_CONVICTION_RECENT_LONG_CONFIRMATION_REQUIRED`.
- ETH second long candidate after short cluster:
  - Recent ETH shorts within 6 minutes: 26.
  - Clean prior longs within 6 minutes: 1.
  - Result after patched guard: `cash/flat`.
  - Rejection: `HIGH_CONVICTION_RECENT_LONG_CONFIRMATION_REQUIRED`.

Interpretation: the previously observed ETH fake-long loss path is blocked by the current strategy.

### Strong-Momentum Paper Evidence

Source: `realtime_candidate_probe13_rotation_holdtp_45m`.

- Decisions: 128.
- Paper tested orders: 4.
- Live orders: 0.
- Closed trades: 11.
- Net realized PnL estimate after fees: `+17.049793`.
- Closed-trade result: 9 wins / 11 total.
- Self-healing status: healthy.
- Protection degraded rate: 0.0.

By symbol:

| Symbol | Trades | Wins | Losses | Net PnL | Max Win | Max Loss | Exit Evidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| PEPEUSDT | 3 | 2 | 1 | +1.299074 | +1.586485 | -0.360000 | proactive partial TP, profit protection partial TP, breakeven stop |
| DOGEUSDT | 2 | 2 | 0 | +6.533031 | +4.899773 | 0.000000 | proactive partial TP, capital reallocation |
| ETHUSDT | 3 | 2 | 1 | +3.298815 | +2.423367 | -0.853826 | proactive partial TP, breakeven stop |
| SOLUSDT | 3 | 3 | 0 | +5.918873 | +2.183152 | 0.000000 | proactive partial TP, profit protection partial TP, capital reallocation |

Interpretation: in a strong long/momentum slice, the rotation candidate entered, partially took profit, protected gains, and rotated capital as intended.

### Weak/Short-Biased Paper Evidence

Source: `realtime_candidate_probe18_longer_reversal_unlock_30m`, stopped at the requested 6-minute mark.

- Decisions: 92.
- Managed futures short signals: 70.
- Prepared live orders: 0.
- Tested orders: 0.
- Closed trades: 0.
- Realized PnL: 0.
- Unrealized futures PnL: 0.
- Self-healing status: healthy.
- Protection degraded rate: 0.0.
- Stderr lines: 0.

Top prepared rejection evidence:

- `LONG_ONLY_TURNAROUND_ENTRY_LONG_ONLY`: 70.
- `DIRECTION_CONFLICT`: 22.
- `EDGE_BELOW_COST`: 22.
- `LIQUIDITY_TOO_WEAK`: 22.
- `SCORE_TOO_LOW`: 22.
- `SUPPORT_NOT_CONFIRMED`: 16.

Interpretation: in a weak or short-biased slice, the strategy did not force long entries. This is intended behavior.

## Current Evidence-Based Verdict

Verified:

- The implementation matches the requested long-only high-conviction structure.
- The known ETH fake-long failure mode is blocked.
- A clean post-short reversal can unlock entry only after 3 qualified long confirmations.
- Strong-momentum paper data shows profitable rotation and partial/protection exits.
- Weak/short-biased paper data shows the bot waits rather than entering long.
- No live orders were placed in these verification runs.

Not guaranteed:

- Future profitability.
- Fill quality under live slippage.
- Performance across all market regimes.
- Avoidance of every fake pump or missed V-reversal.

Recommended next verification:

- Run several short paper windows across different market regimes.
- Track blocked long candidates for missed breakout versus avoided loss.
- Tune the clean-reversal unlock count only from comparative paper evidence.
