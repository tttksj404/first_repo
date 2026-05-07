from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from quant_binance.execution.binance_rest import BinanceRestClient
from quant_binance.settings import Settings


@dataclass(frozen=True)
class CapitalRequirement:
    symbol: str
    market: str
    min_notional_usd: float
    min_equity_usd: float
    buffered_min_equity_usd: float


@dataclass(frozen=True)
class CapitalAdequacyReport:
    spot_available_balance_usd: float
    futures_available_balance_usd: float
    minimum_operational_balance_usd: float
    minimum_full_universe_balance_usd: float
    recommended_balance_usd: float
    can_trade_any: bool
    can_trade_spot_any: bool
    can_trade_futures_any: bool
    spot_requirements: tuple[CapitalRequirement, ...]
    futures_requirements: tuple[CapitalRequirement, ...]
    pending_symbols: tuple[str, ...]
    note: str


def _symbol_min_notional(exchange_info: dict[str, Any], symbol: str) -> float:
    for item in exchange_info["symbols"]:
        if item["symbol"] != symbol:
            continue
        for filt in item["filters"]:
            if filt["filterType"] in {"MIN_NOTIONAL", "NOTIONAL"}:
                value = filt.get("notional") or filt.get("minNotional")
                return float(value)
    raise KeyError(f"min notional not found for {symbol}")


def split_supported_symbols(
    *,
    symbols: tuple[str, ...],
    rest_client: BinanceRestClient,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    spot_info = rest_client.get_exchange_info(market="spot")
    futures_info = rest_client.get_exchange_info(market="futures")
    spot_symbols = {item["symbol"] for item in spot_info["symbols"]}
    futures_symbols = {item["symbol"] for item in futures_info["symbols"]}
    spot_active: list[str] = []
    futures_active: list[str] = []
    pending: list[str] = []
    for symbol in symbols:
        supported = False
        if symbol in spot_symbols:
            spot_active.append(symbol)
            supported = True
        if symbol in futures_symbols:
            futures_active.append(symbol)
            supported = True
        if not supported:
            pending.append(symbol)
    return tuple(spot_active), tuple(futures_active), tuple(pending)


def build_capital_adequacy_report(
    *,
    spot_available_balance_usd: float,
    futures_available_balance_usd: float,
    settings: Settings,
    rest_client: BinanceRestClient,
) -> CapitalAdequacyReport:
    spot_exchange_info = rest_client.get_exchange_info(market="spot")
    futures_exchange_info = rest_client.get_exchange_info(market="futures")
    spot_symbols, futures_symbols, pending_symbols = split_supported_symbols(
        symbols=settings.universe,
        rest_client=rest_client,
    )
    cap_fraction = settings.risk.max_symbol_notional_fraction
    spot_requirements: list[CapitalRequirement] = []
    futures_requirements: list[CapitalRequirement] = []
    for symbol in spot_symbols:
        min_notional = _symbol_min_notional(spot_exchange_info, symbol)
        min_equity = min_notional / cap_fraction
        buffered = min_equity * 1.25
        spot_requirements.append(
            CapitalRequirement(
                symbol=symbol,
                market="spot",
                min_notional_usd=min_notional,
                min_equity_usd=round(min_equity, 6),
                buffered_min_equity_usd=round(buffered, 6),
            )
        )
    for symbol in futures_symbols:
        min_notional = _symbol_min_notional(futures_exchange_info, symbol)
        min_equity = min_notional / cap_fraction
        buffered = min_equity * 1.25
        futures_requirements.append(
            CapitalRequirement(
                symbol=symbol,
                market="futures",
                min_notional_usd=min_notional,
                min_equity_usd=round(min_equity, 6),
                buffered_min_equity_usd=round(buffered, 6),
            )
        )
    all_requirements = [*spot_requirements, *futures_requirements]
    minimum_operational = min(item.buffered_min_equity_usd for item in all_requirements)
    minimum_full_universe = max(item.buffered_min_equity_usd for item in all_requirements)
    recommended = round(minimum_full_universe * 1.6, 6)
    can_trade_spot_any = any(
        spot_available_balance_usd >= item.buffered_min_equity_usd for item in spot_requirements
    )
    can_trade_futures_any = any(
        futures_available_balance_usd >= item.buffered_min_equity_usd for item in futures_requirements
    )
    can_trade_any = can_trade_spot_any or can_trade_futures_any
    note = (
        "5% 수익 보장은 불가하며, 아래 금액은 현재 설정과 최소 주문 조건 기준의 운영 가능 자금 추정치입니다."
    )
    if pending_symbols:
        note += f" Pending symbols excluded from capital check: {', '.join(pending_symbols)}."
    return CapitalAdequacyReport(
        spot_available_balance_usd=spot_available_balance_usd,
        futures_available_balance_usd=futures_available_balance_usd,
        minimum_operational_balance_usd=round(minimum_operational, 6),
        minimum_full_universe_balance_usd=round(minimum_full_universe, 6),
        recommended_balance_usd=recommended,
        can_trade_any=can_trade_any,
        can_trade_spot_any=can_trade_spot_any,
        can_trade_futures_any=can_trade_futures_any,
        spot_requirements=tuple(spot_requirements),
        futures_requirements=tuple(futures_requirements),
        pending_symbols=tuple(pending_symbols),
        note=note,
    )
