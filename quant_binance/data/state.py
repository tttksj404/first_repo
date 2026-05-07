from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class TopOfBook:
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    updated_at: datetime


@dataclass(frozen=True)
class SpotTrade:
    symbol: str
    price: float
    quantity: float
    event_time: datetime
    is_buyer_maker: bool


@dataclass(frozen=True)
class KlineBar:
    symbol: str
    interval: str
    start_time: datetime
    close_time: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    quote_volume: float
    is_closed: bool


@dataclass
class SymbolMarketState:
    symbol: str
    top_of_book: TopOfBook
    last_trade_price: float
    funding_rate: float
    open_interest: float
    basis_bps: float
    last_update_time: datetime
    trades: list[SpotTrade] = field(default_factory=list)
    klines: dict[str, list[KlineBar]] = field(default_factory=dict)
    order_book_imbalance_samples: list[float] = field(default_factory=list)
    funding_rate_samples: list[float] = field(default_factory=list)
    basis_bps_samples: list[float] = field(default_factory=list)
    open_interest_samples: list[float] = field(default_factory=list)

    def freshness_ms(self, now: datetime) -> int:
        return int((now - self.last_update_time).total_seconds() * 1000)
