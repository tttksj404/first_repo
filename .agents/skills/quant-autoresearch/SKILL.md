---
name: quant-autoresearch
description: Run an AutoResearch-style experiment loop for quant trading strategy tuning using replay, paper, logs, and comparative evaluation. Use when the user asks to optimize, tune, compare, iterate, run experiments, search parameters, improve strategy performance, or automatically test multiple strategy variants before live deployment.
---

# Quant AutoResearch

## Purpose

Use an experiment loop instead of one-shot guesswork when tuning trading strategy behavior.

This skill is for:
- parameter sweeps
- strategy variant comparison
- replay or paper validation
- repeated evaluation of entry gates, leverage, sizing, and rejection logic
- narrowing candidate configurations before any live change

Do **not** use this as direct justification for immediate live deployment without a replay/paper evidence pass.

## Workflow

1. Define the target question narrowly.
   - Examples:
     - increase futures participation without reckless churn
     - compare leverage profiles for small capital
     - reduce flat/cash outcomes in down markets
2. Pick a small experiment surface.
   - Change only a few parameters per round.
   - Prefer 3-8 variants, not dozens at once.
3. Run each variant in a safe evaluation mode.
   - Prefer replay, paper, or other non-live validation paths.
4. Collect the same metrics for every run.
   - decision counts
   - mode distribution
   - long/short split
   - rejection reasons
   - order count
   - error count
   - pnl or proxy performance if available
5. Rank results by evidence, not intuition.
6. Keep only the strongest candidates.
7. Summarize:
   - what changed
   - what improved
   - what regressed
   - what should be tested next
8. Only after a good replay/paper result, propose a live candidate.

## Default experiment structure

For each round, report:
- Goal
- Variants tested
- Metrics observed
- Best candidate
- Risks
- Next round

## Rules

- Prefer fewer, interpretable experiments over wide random mutation.
- Keep a baseline run for comparison.
- Do not treat a single strong run as proof.
- Watch for overfitting to one market slice.
- If live trading is involved later, require an explicit human go-ahead.

## Good triggers

Use this skill when the request sounds like:
- "전략 자동 튜닝해봐"
- "파라미터 여러 개 비교해봐"
- "어떤 설정이 더 나은지 실험해봐"
- "자동으로 반복 실험해서 최적화해"
- "live 넣기 전에 paper로 돌려봐"
