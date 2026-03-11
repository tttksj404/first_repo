from __future__ import annotations

from typing import Any

from quant_binance.exchange import ExchangeCredentials, load_exchange_credentials_from_env, resolve_exchange_id
from quant_binance.execution.binance_rest import BinanceCredentials, BinanceRestClient
from quant_binance.execution.bitget_rest import BitgetRestClient


def build_exchange_rest_client(
    *,
    exchange: str | None = None,
    allow_insecure_ssl: bool = False,
    allow_missing_credentials: bool = False,
) -> Any:
    credentials = load_exchange_credentials_from_env(exchange, allow_missing=allow_missing_credentials)
    return build_rest_client_from_credentials(
        credentials=credentials,
        allow_insecure_ssl=allow_insecure_ssl,
    )


def build_rest_client_from_credentials(
    *,
    credentials: ExchangeCredentials,
    allow_insecure_ssl: bool = False,
) -> Any:
    exchange_id = resolve_exchange_id(credentials.exchange_id)
    if exchange_id == "bitget":
        usable_credentials = credentials if credentials.api_key or credentials.api_secret or credentials.api_passphrase else None
        return BitgetRestClient(
            credentials=usable_credentials,
            allow_insecure_ssl=allow_insecure_ssl,
        )
    return BinanceRestClient(
        credentials=BinanceCredentials(
            api_key=credentials.api_key,
            api_secret=credentials.api_secret,
        ),
        allow_insecure_ssl=allow_insecure_ssl,
    )
