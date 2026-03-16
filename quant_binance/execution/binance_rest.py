from __future__ import annotations

import hashlib
import hmac
import json
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import Request, urlopen


BINANCE_SPOT_REST_URL = "https://api.binance.com"
BINANCE_FUTURES_REST_URL = "https://fapi.binance.com"


def _transport_error_message(*, request: Request, exc: URLError) -> str:
    reason = exc.reason
    target = request.full_url
    host = getattr(getattr(request, "host", None), "strip", lambda: "")() or "unknown-host"
    if isinstance(reason, socket.gaierror):
        return f"Binance transport error for {target} (host={host}): DNS resolution failed: {reason}"
    return f"Binance transport error for {target} (host={host}): {reason}"


def sign_query_string(secret: str, params: dict[str, Any]) -> tuple[str, str]:
    encoded = urlencode(sorted((key, value) for key, value in params.items() if value is not None))
    signature = hmac.new(
        secret.encode("utf-8"),
        encoded.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return encoded, signature


@dataclass(frozen=True)
class BinanceCredentials:
    api_key: str
    api_secret: str


class BinanceRestClient:
    def __init__(
        self,
        *,
        credentials: BinanceCredentials,
        spot_base_url: str = BINANCE_SPOT_REST_URL,
        futures_base_url: str = BINANCE_FUTURES_REST_URL,
        recv_window: int = 5000,
        allow_insecure_ssl: bool = False,
    ) -> None:
        self.credentials = credentials
        self.spot_base_url = spot_base_url.rstrip("/")
        self.futures_base_url = futures_base_url.rstrip("/")
        self.recv_window = recv_window
        self.allow_insecure_ssl = allow_insecure_ssl

    def signed_params(self, params: dict[str, Any]) -> dict[str, Any]:
        signed = dict(params)
        signed.setdefault("timestamp", int(time.time() * 1000))
        signed.setdefault("recvWindow", self.recv_window)
        return signed

    def build_signed_request(
        self,
        *,
        market: str,
        path: str,
        method: str,
        params: dict[str, Any],
    ) -> Request:
        base_url = self.futures_base_url if market == "futures" else self.spot_base_url
        signed = self.signed_params(params)
        query, signature = sign_query_string(self.credentials.api_secret, signed)
        url = f"{base_url}{path}?{query}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.credentials.api_key}
        return Request(url=url, method=method.upper(), headers=headers)

    def build_public_request(
        self,
        *,
        market: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Request:
        base_url = self.futures_base_url if market == "futures" else self.spot_base_url
        query = urlencode(sorted((key, value) for key, value in (params or {}).items() if value is not None))
        url = f"{base_url}{path}"
        if query:
            url = f"{url}?{query}"
        return Request(url=url, method="GET")

    def build_order_params(
        self,
        *,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: float | None = None,
        reduce_only: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": f"{quantity:.8f}",
        }
        if price is not None:
            payload["price"] = f"{price:.8f}"
            payload["timeInForce"] = "GTC"
        if reduce_only is not None:
            payload["reduceOnly"] = "true" if reduce_only else "false"
        return payload

    def build_account_request(self, *, market: str) -> Request:
        path = "/fapi/v2/account" if market == "futures" else "/api/v3/account"
        return self.build_signed_request(market=market, path=path, method="GET", params={})

    def build_open_orders_request(self, *, market: str, symbol: str | None = None) -> Request:
        path = "/fapi/v1/openOrders" if market == "futures" else "/api/v3/openOrders"
        params = {"symbol": symbol} if symbol else {}
        return self.build_signed_request(market=market, path=path, method="GET", params=params)

    def build_test_order_request(
        self,
        *,
        market: str,
        order_params: dict[str, Any],
    ) -> Request:
        path = "/fapi/v1/order/test" if market == "futures" else "/api/v3/order/test"
        return self.build_signed_request(
            market=market,
            path=path,
            method="POST",
            params=order_params,
        )

    def build_live_order_request(
        self,
        *,
        market: str,
        order_params: dict[str, Any],
    ) -> Request:
        path = "/fapi/v1/order" if market == "futures" else "/api/v3/order"
        return self.build_signed_request(
            market=market,
            path=path,
            method="POST",
            params=order_params,
        )

    def build_asset_transfer_request(
        self,
        *,
        source_market: str,
        target_market: str,
        asset: str,
        amount: float,
    ) -> Request:
        transfer_type = {
            ("spot", "futures"): "MAIN_UMFUTURE",
            ("futures", "spot"): "UMFUTURE_MAIN",
        }.get((source_market, target_market))
        if transfer_type is None:
            raise ValueError(f"unsupported Binance transfer route {source_market!r}->{target_market!r}")
        return self.build_signed_request(
            market="spot",
            path="/sapi/v1/asset/transfer",
            method="POST",
            params={
                "type": transfer_type,
                "asset": asset.upper(),
                "amount": f"{float(amount):.8f}",
            },
        )

    def get_account(self, *, market: str) -> dict[str, Any]:
        return self.send(self.build_account_request(market=market))

    def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, Any]:
        return self.send(self.build_open_orders_request(market=market, symbol=symbol))

    def test_order(self, *, market: str, order_params: dict[str, Any]) -> dict[str, Any]:
        return self.send(self.build_test_order_request(market=market, order_params=order_params))

    def place_order(self, *, market: str, order_params: dict[str, Any]) -> dict[str, Any]:
        return self.send(self.build_live_order_request(market=market, order_params=order_params))

    def transfer_asset(
        self,
        *,
        source_market: str,
        target_market: str,
        asset: str,
        amount: float,
        client_oid: str | None = None,
    ) -> dict[str, Any]:
        del client_oid
        return self.send(
            self.build_asset_transfer_request(
                source_market=source_market,
                target_market=target_market,
                asset=asset,
                amount=amount,
            )
        )

    def transfer_wallet_balance(
        self,
        *,
        asset: str,
        amount: float,
        source_market: str,
        target_market: str,
    ) -> dict[str, Any]:
        transfer_type_map = {
            ("spot", "futures"): "MAIN_UMFUTURE",
            ("futures", "spot"): "UMFUTURE_MAIN",
        }
        transfer_type = transfer_type_map.get((source_market, target_market))
        if transfer_type is None:
            raise ValueError(f"unsupported Binance wallet transfer route {source_market}->{target_market}")
        request = self.build_signed_request(
            market="spot",
            path="/sapi/v1/asset/transfer",
            method="POST",
            params={
                "type": transfer_type,
                "asset": asset.upper(),
                "amount": f"{max(float(amount), 0.0):.8f}",
            },
        )
        return self.send(request)

    def set_futures_leverage(self, *, symbol: str, leverage: int) -> dict[str, Any]:
        request = self.build_signed_request(
            market="futures",
            path="/fapi/v1/leverage",
            method="POST",
            params={"symbol": symbol, "leverage": leverage},
        )
        return self.send(request)

    def get_klines(
        self,
        *,
        market: str,
        symbol: str,
        interval: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        path = "/fapi/v1/klines" if market == "futures" else "/api/v3/klines"
        request = self.build_public_request(
            market=market,
            path=path,
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        data = self.send(request)
        if isinstance(data, list):
            return data
        raise RuntimeError("unexpected kline response shape")

    def get_book_ticker(self, *, market: str, symbol: str) -> dict[str, Any]:
        path = "/fapi/v1/ticker/bookTicker" if market == "futures" else "/api/v3/ticker/bookTicker"
        return self.send(
            self.build_public_request(market=market, path=path, params={"symbol": symbol})
        )

    def get_mark_price(self, *, symbol: str) -> dict[str, Any]:
        return self.send(
            self.build_public_request(
                market="futures",
                path="/fapi/v1/premiumIndex",
                params={"symbol": symbol},
            )
        )

    def get_open_interest(self, *, symbol: str) -> dict[str, Any]:
        return self.send(
            self.build_public_request(
                market="futures",
                path="/fapi/v1/openInterest",
                params={"symbol": symbol},
            )
        )

    def get_exchange_info(self, *, market: str) -> dict[str, Any]:
        path = "/fapi/v1/exchangeInfo" if market == "futures" else "/api/v3/exchangeInfo"
        return self.send(self.build_public_request(market=market, path=path))

    def send(self, request: Request) -> dict[str, Any]:
        context = None
        if self.allow_insecure_ssl:
            context = ssl._create_unverified_context()
        try:
            with urlopen(request, timeout=10, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        except URLError as exc:
            raise RuntimeError(_transport_error_message(request=request, exc=exc)) from exc
