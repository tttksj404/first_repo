"""Execution adapters and routing."""

from .binance_rest import BinanceRestClient, sign_query_string
from .bitget_rest import BitgetRestClient, sign_bitget_request
from .client_factory import build_exchange_rest_client, build_rest_client_from_credentials
from .live_order_adapter import DecisionLiveOrderAdapter, LiveOrderResult
from .order_test_adapter import DecisionOrderTestAdapter, OrderTestResult
from .paper_broker import PaperBroker, PaperOrder
from .router import ExecutionRouter

__all__ = [
    "BinanceRestClient",
    "BitgetRestClient",
    "DecisionLiveOrderAdapter",
    "DecisionOrderTestAdapter",
    "ExecutionRouter",
    "LiveOrderResult",
    "OrderTestResult",
    "PaperBroker",
    "PaperOrder",
    "build_exchange_rest_client",
    "build_rest_client_from_credentials",
    "sign_bitget_request",
    "sign_query_string",
]
