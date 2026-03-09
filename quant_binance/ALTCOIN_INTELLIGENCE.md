# Altcoin Intelligence Inputs

This layer adds external altcoin-strategy context on top of the existing market, macro, and sentiment logic.

## Recommended Source Stack

- `CoinGecko`
  - Use for: broad alt universe discovery, category momentum, market-cap/liquidity ranking, trending.
  - Role in system: `category_momentum_score`, candidate-universe ranking.
  - Official docs: [API overview](https://docs.coingecko.com/) and [SDK](https://docs.coingecko.com/docs/sdk)
- `DefiLlama`
  - Use for: chain/protocol TVL, stablecoin flows, fees, perps context.
  - Role in system: `stablecoin_flow_score`, sector-level liquidity support.
  - Official docs: [Pro API docs](https://defillama.com/pro-api/docs)
- `Nansen`
  - Use for: smart-money wallet/entity flows and accumulation.
  - Role in system: `smart_money_score`.
  - Official docs: [API intro](https://docs.nansen.ai/) and [authentication](https://docs.nansen.ai/getting-started/authentication)
- `Token Terminal`
  - Use for: protocol fundamentals, fees/revenue/earnings.
  - Role in system: `fundamental_score`.
  - Official docs: [API reference](https://docs.tokenterminal.com/reference/api-reference)
- `Glassnode` / `Kaiko`
  - Use later for: proprietary regime breadth or institutional-grade liquidity checks.
  - Role in system: refine `alt_breadth_score`, `alt_liquidity_score`.
  - Official docs:
    - [Glassnode API](https://docs.glassnode.com/basic-api/api)
    - [Kaiko Developer Hub](https://docs.kaiko.com/)

## Input Schema

Use `ALTCOIN_INPUTS_PATH` or `ALTCOIN_INPUTS_JSON`.

Global fields:
- `alt_breadth_score`
- `alt_liquidity_score`
- `stablecoin_flow_score`
- `btc_dominance_penalty`

Per-symbol fields:
- `smart_money_score`
- `fundamental_score`
- `category_momentum_score`
- `fdv_stress_penalty`
- `unlock_risk_penalty`

## Strategy Mapping

- `alt_breadth_score`
  - Broad alt participation from CoinGecko category breadth, DefiLlama sector breadth, or Glassnode-style alt regime metrics.
- `alt_liquidity_score`
  - Use CoinGecko/Kaiko/DefiLlama liquidity proxies.
- `stablecoin_flow_score`
  - Prefer DefiLlama stablecoin/chain inflow metrics.
- `btc_dominance_penalty`
  - High when BTC dominance rises and alt rotation weakens.
- `smart_money_score`
  - Prefer Nansen smart-money netflow or labeled-wallet accumulation.
- `fundamental_score`
  - Prefer Token Terminal fees/revenue/earnings growth.
- `category_momentum_score`
  - Prefer CoinGecko category and narrative strength.
- `fdv_stress_penalty`
  - Penalize high fully-diluted-valuation stress or poor float structure.
- `unlock_risk_penalty`
  - Penalize near-term unlock overhang.

## Runtime Effect

- Alt symbols receive additional support or penalty before regime selection.
- The overlay influences:
  - gross edge estimation
  - spot/futures pass/fail for altcoins
  - market regime labeling for alts

`BTCUSDT` and `ETHUSDT` are treated as majors and bypass this overlay.
