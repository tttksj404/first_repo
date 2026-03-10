from __future__ import annotations

from quant_binance.settings import Settings


def position_notional_and_stop_bps(
    *,
    last_trade_price: float,
    atr_14_1h_bps: float,
    equity_usd: float,
    remaining_portfolio_capacity_usd: float,
    settings: Settings,
    size_multiplier: float = 1.0,
) -> tuple[float, float]:
    stop_distance_bps = max(
        settings.sizing.atr_multiple_for_stop * atr_14_1h_bps,
        settings.sizing.stop_floor_bps,
    )
    risk_dollars = equity_usd * settings.risk.per_trade_equity_risk
    adjusted_size_multiplier = max(size_multiplier, 0.0)
    raw_notional_usd = (
        risk_dollars / (stop_distance_bps / 10000.0) * adjusted_size_multiplier
    )
    symbol_cap_multiplier = max(adjusted_size_multiplier, 1.0)
    capped_notional = min(
        raw_notional_usd,
        equity_usd * settings.risk.max_symbol_notional_fraction * symbol_cap_multiplier,
        remaining_portfolio_capacity_usd,
    )
    return round(capped_notional, 6), round(stop_distance_bps, 6)


def quantity_from_notional(notional_usd: float, reference_price: float) -> float:
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    return round(notional_usd / reference_price, 8)
