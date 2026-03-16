from __future__ import annotations

import base64
import hashlib
import hmac
import json
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from quant_binance.exchange import ExchangeCredentials


BITGET_REST_URL = "https://api.bitget.com"
BITGET_DEFAULT_PRODUCT_TYPE = "USDT-FUTURES"
BITGET_DEFAULT_MARGIN_COIN = "USDT"


def _transport_error_message(*, request: Request, exc: URLError) -> str:
    reason = exc.reason
    target = request.full_url
    host = getattr(getattr(request, "host", None), "strip", lambda: "")() or "unknown-host"
    if isinstance(reason, socket.gaierror):
        return f"Bitget transport error for {target} (host={host}): DNS resolution failed: {reason}"
    return f"Bitget transport error for {target} (host={host}): {reason}"


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _bitget_futures_side(*, side: str, reduce_only: bool | None) -> str:
    normalized = side.strip().upper()
    if normalized not in {"BUY", "SELL"}:
        raise ValueError(f"unsupported Bitget futures side '{side}'")
    return normalized.lower()


_SPOT_KLINE_GRANULARITY = {
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "6h": "6h",
    "12h": "12h",
    "1d": "1day",
    "1w": "1week",
    "1M": "1M",
}

_FUTURES_KLINE_GRANULARITY = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "4h": "4H",
    "6h": "6H",
    "12h": "12H",
    "1d": "1D",
    "1w": "1W",
    "1M": "1M",
}


def _bitget_granularity(*, market: str, interval: str) -> str:
    if market == "futures":
        return _FUTURES_KLINE_GRANULARITY.get(interval, interval)
    return _SPOT_KLINE_GRANULARITY.get(interval, interval)


def _json_body(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def sign_bitget_request(
    *,
    secret: str,
    timestamp_ms: int,
    method: str,
    request_path: str,
    query_string: str = "",
    body: str = "",
) -> str:
    payload = f"{timestamp_ms}{method.upper()}{request_path}"
    if query_string:
        payload += f"?{query_string}"
    payload += body
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


@dataclass(frozen=True)
class BitgetContractConfig:
    product_type: str = BITGET_DEFAULT_PRODUCT_TYPE
    margin_coin: str = BITGET_DEFAULT_MARGIN_COIN


class BitgetRestClient:
    exchange_id = "bitget"

    def __init__(
        self,
        *,
        credentials: ExchangeCredentials | None = None,
        base_url: str = BITGET_REST_URL,
        contract_config: BitgetContractConfig | None = None,
        receive_window_ms: int = 5000,
        allow_insecure_ssl: bool = False,
    ) -> None:
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.contract_config = contract_config or BitgetContractConfig()
        self.receive_window_ms = receive_window_ms
        self.allow_insecure_ssl = allow_insecure_ssl

    @property
    def supports_private_reads(self) -> bool:
        return self.credentials is not None and bool(self.credentials.api_key and self.credentials.api_secret and self.credentials.api_passphrase)

    def _require_credentials(self) -> ExchangeCredentials:
        if not self.supports_private_reads or self.credentials is None:
            raise RuntimeError("Bitget private API access requires BITGET_API_KEY, BITGET_API_SECRET, and BITGET_API_PASSPHRASE")
        return self.credentials

    def build_public_request(
        self,
        *,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Request:
        query = urlencode(sorted((key, value) for key, value in (params or {}).items() if value is not None))
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        return Request(url=url, method="GET")

    def build_signed_request(
        self,
        *,
        path: str,
        method: str,
        params: dict[str, Any] | None = None,
        body_params: dict[str, Any] | None = None,
    ) -> Request:
        credentials = self._require_credentials()
        timestamp_ms = int(time.time() * 1000)
        query = urlencode(sorted((key, value) for key, value in (params or {}).items() if value is not None))
        body = _json_body(body_params)
        sign = sign_bitget_request(
            secret=credentials.api_secret,
            timestamp_ms=timestamp_ms,
            method=method,
            request_path=path,
            query_string=query,
            body=body,
        )
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        headers = {
            "ACCESS-KEY": credentials.api_key,
            "ACCESS-SIGN": sign,
            "ACCESS-TIMESTAMP": str(timestamp_ms),
            "ACCESS-PASSPHRASE": credentials.api_passphrase,
            "Content-Type": "application/json",
            "locale": "en-US",
        }
        data = body.encode("utf-8") if body else None
        return Request(url=url, method=method.upper(), headers=headers, data=data)

    def build_account_request(self, *, market: str) -> Request:
        if market == "futures":
            return self.build_signed_request(
                path="/api/v2/mix/account/accounts",
                method="GET",
                params={"productType": self.contract_config.product_type},
            )
        return self.build_signed_request(
            path="/api/v2/spot/account/assets",
            method="GET",
            params={"assetType": "hold_only"},
        )

    def build_open_orders_request(self, *, market: str, symbol: str | None = None) -> Request:
        if market == "futures":
            params = {"productType": self.contract_config.product_type, "symbol": symbol}
            return self.build_signed_request(
                path="/api/v2/mix/order/orders-pending",
                method="GET",
                params=params,
            )
        return self.build_signed_request(
            path="/api/v2/spot/trade/unfilled-orders",
            method="GET",
            params={"symbol": symbol},
        )

    def build_positions_request(self) -> Request:
        return self.build_signed_request(
            path="/api/v2/mix/position/all-position",
            method="GET",
            params={
                "productType": self.contract_config.product_type,
                "marginCoin": self.contract_config.margin_coin,
            },
        )

    def build_futures_order_history_request(
        self,
        *,
        symbol: str | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        id_less_than: str | None = None,
        limit: int = 100,
    ) -> Request:
        return self.build_signed_request(
            path="/api/v2/mix/order/orders-history",
            method="GET",
            params={
                "productType": self.contract_config.product_type,
                "symbol": symbol,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "idLessThan": id_less_than,
                "limit": limit,
            },
        )

    def build_futures_fill_history_request(
        self,
        *,
        symbol: str | None = None,
        order_id: str | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        id_less_than: str | None = None,
        limit: int = 100,
    ) -> Request:
        return self.build_signed_request(
            path="/api/v2/mix/order/fill-history",
            method="GET",
            params={
                "productType": self.contract_config.product_type,
                "symbol": symbol,
                "orderId": order_id,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "idLessThan": id_less_than,
                "limit": limit,
            },
        )

    def build_futures_position_history_request(
        self,
        *,
        symbol: str | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        id_less_than: str | None = None,
        limit: int = 100,
    ) -> Request:
        return self.build_signed_request(
            path="/api/v2/mix/position/history-position",
            method="GET",
            params={
                "productType": self.contract_config.product_type,
                "symbol": symbol,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "idLessThan": id_less_than,
                "limit": limit,
            },
        )

    def build_live_order_request(self, *, market: str, order_params: dict[str, Any]) -> Request:
        if market == "futures":
            return self.build_signed_request(
                path="/api/v2/mix/order/place-order",
                method="POST",
                body_params=order_params,
            )
        return self.build_signed_request(
            path="/api/v2/spot/trade/place-order",
            method="POST",
            body_params=order_params,
        )

    def build_futures_position_tpsl_request(self, *, order_params: dict[str, Any]) -> Request:
        return self.build_signed_request(
            path="/api/v2/mix/order/place-pos-tpsl",
            method="POST",
            body_params=order_params,
        )

    def build_futures_pending_plan_orders_request(
        self,
        *,
        symbol: str | None = None,
        plan_type: str = "profit_loss",
        order_id: str | None = None,
        client_oid: str | None = None,
    ) -> Request:
        return self.build_signed_request(
            path="/api/v2/mix/order/orders-plan-pending",
            method="GET",
            params={
                "productType": self.contract_config.product_type,
                "symbol": symbol,
                "planType": plan_type,
                "orderId": order_id,
                "clientOid": client_oid,
            },
        )

    def build_cancel_futures_plan_order_request(
        self,
        *,
        symbol: str,
        order_id_list: list[dict[str, str]],
        plan_type: str | None = None,
    ) -> Request:
        return self.build_signed_request(
            path="/api/v2/mix/order/cancel-plan-order",
            method="POST",
            body_params={
                "symbol": symbol,
                "productType": self.contract_config.product_type,
                "marginCoin": self.contract_config.margin_coin,
                "planType": plan_type,
                "orderIdList": order_id_list,
            },
        )

    def build_cancel_order_request(self, *, market: str, symbol: str, order_id: str) -> Request:
        if market == "futures":
            return self.build_signed_request(
                path="/api/v2/mix/order/cancel-order",
                method="POST",
                body_params={
                    "symbol": symbol,
                    "productType": self.contract_config.product_type,
                    "marginCoin": self.contract_config.margin_coin,
                    "orderId": order_id,
                },
            )
        return self.build_signed_request(
            path="/api/v2/spot/trade/cancel-order",
            method="POST",
            body_params={"symbol": symbol, "orderId": order_id},
        )

    def build_spot_plan_order_request(self, *, order_params: dict[str, Any]) -> Request:
        return self.build_signed_request(
            path="/api/v2/spot/trade/place-plan-order",
            method="POST",
            body_params=order_params,
        )

    def build_wallet_transfer_request(
        self,
        *,
        source_market: str,
        target_market: str,
        asset: str,
        amount: float,
        client_oid: str | None = None,
    ) -> Request:
        type_map = {
            ("spot", "futures"): ("spot", "usdt_futures"),
            ("futures", "spot"): ("usdt_futures", "spot"),
        }
        from_type, to_type = type_map.get((source_market, target_market), ("", ""))
        if not from_type or not to_type:
            raise ValueError(f"unsupported Bitget transfer route {source_market!r}->{target_market!r}")
        body_params: dict[str, Any] = {
            "fromType": from_type,
            "toType": to_type,
            "coin": asset.upper(),
            "amount": f"{float(amount):.8f}",
        }
        if client_oid:
            body_params["clientOid"] = client_oid
        return self.build_signed_request(
            path="/api/v2/spot/wallet/transfer",
            method="POST",
            body_params=body_params,
        )

    def build_order_params(
        self,
        *,
        market: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        notional_usd: float | None = None,
        reduce_only: bool | None = None,
        client_oid: str | None = None,
    ) -> dict[str, Any]:
        if market == "spot":
            payload: dict[str, Any] = {
                "symbol": symbol,
                "side": side.lower(),
                "orderType": order_type.lower(),
            }
            if side.upper() == "BUY" and notional_usd is not None:
                payload["size"] = f"{notional_usd:.2f}"
            else:
                payload["size"] = f"{quantity:.8f}"
            if client_oid:
                payload["clientOid"] = client_oid
            return payload
        raw: dict[str, Any] = {}
        try:
            exchange_info = self.get_exchange_info(market="futures")
        except Exception:
            exchange_info = {"symbols": []}
        symbol_row = next((item for item in exchange_info.get("symbols", []) if item.get("symbol") == symbol), None)
        raw = dict(symbol_row.get("raw") or {}) if isinstance(symbol_row, dict) else {}
        volume_place = raw.get("volumePlace")
        try:
            precision = max(int(volume_place), 0)
        except (TypeError, ValueError):
            precision = 8
        payload = {
            "symbol": symbol,
            "productType": self.contract_config.product_type,
            "marginCoin": self.contract_config.margin_coin,
            "marginMode": "crossed",
            "side": _bitget_futures_side(side=side, reduce_only=reduce_only),
            "tradeSide": "close" if reduce_only else "open",
            "orderType": order_type.lower(),
            "size": f"{quantity:.{precision}f}",
        }
        if client_oid:
            payload["clientOid"] = client_oid
        return payload

    def test_order(self, *, market: str, order_params: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "PREVIEW",
            "exchange": self.exchange_id,
            "market": market,
            "request": dict(order_params),
            "note": "Bitget has no Binance-style order/test REST endpoint; this first pass performs local payload preview only.",
        }

    def place_order(self, *, market: str, order_params: dict[str, Any]) -> dict[str, Any]:
        payload = self.send(self.build_live_order_request(market=market, order_params=order_params))
        data = payload.get("data")
        normalized: dict[str, Any] = {
            "status": "SUCCESS" if payload.get("code") == "00000" else str(payload.get("msg", "error")).upper(),
            "exchange": self.exchange_id,
            "market": market,
            "raw": payload,
        }
        if isinstance(data, dict):
            normalized.update(data)
        return normalized

    def place_futures_position_tpsl(self, *, order_params: dict[str, Any]) -> dict[str, Any]:
        payload = self.send(self.build_futures_position_tpsl_request(order_params=order_params))
        data = payload.get("data")
        normalized: dict[str, Any] = {
            "status": "SUCCESS" if payload.get("code") == "00000" else str(payload.get("msg", "error")).upper(),
            "exchange": self.exchange_id,
            "market": "futures",
            "raw": payload,
        }
        if isinstance(data, dict):
            normalized.update(data)
        return normalized

    def get_futures_pending_plan_orders(
        self,
        *,
        symbol: str | None = None,
        plan_type: str = "profit_loss",
        order_id: str | None = None,
        client_oid: str | None = None,
    ) -> dict[str, Any]:
        payload = self.send(
            self.build_futures_pending_plan_orders_request(
                symbol=symbol,
                plan_type=plan_type,
                order_id=order_id,
                client_oid=client_oid,
            )
        )
        rows, end_id = self._extract_paged_rows(payload)
        return {"orders": rows, "endId": end_id, "raw": payload}

    def cancel_futures_plan_orders(
        self,
        *,
        symbol: str,
        order_id_list: list[dict[str, str]],
        plan_type: str | None = None,
    ) -> dict[str, Any]:
        payload = self.send(
            self.build_cancel_futures_plan_order_request(
                symbol=symbol,
                order_id_list=order_id_list,
                plan_type=plan_type,
            )
        )
        data = payload.get("data")
        normalized: dict[str, Any] = {
            "status": "SUCCESS" if payload.get("code") == "00000" else str(payload.get("msg", "error")).upper(),
            "exchange": self.exchange_id,
            "market": "futures",
            "raw": payload,
        }
        if isinstance(data, dict):
            normalized.update(data)
        return normalized

    def place_spot_plan_order(self, *, order_params: dict[str, Any]) -> dict[str, Any]:
        payload = self.send(self.build_spot_plan_order_request(order_params=order_params))
        data = payload.get("data")
        normalized: dict[str, Any] = {
            "status": "SUCCESS" if payload.get("code") == "00000" else str(payload.get("msg", "error")).upper(),
            "exchange": self.exchange_id,
            "market": "spot",
            "raw": payload,
        }
        if isinstance(data, dict):
            normalized.update(data)
        return normalized

    def transfer_asset(
        self,
        *,
        source_market: str,
        target_market: str,
        asset: str,
        amount: float,
        client_oid: str | None = None,
    ) -> dict[str, Any]:
        payload = self.send(
            self.build_wallet_transfer_request(
                source_market=source_market,
                target_market=target_market,
                asset=asset,
                amount=amount,
                client_oid=client_oid,
            )
        )
        data = payload.get("data")
        normalized: dict[str, Any] = {
            "status": "SUCCESS" if payload.get("code") == "00000" else str(payload.get("msg", "error")).upper(),
            "exchange": self.exchange_id,
            "raw": payload,
        }
        if isinstance(data, dict):
            normalized.update(data)
        return normalized

    def transfer_wallet_balance(
        self,
        *,
        asset: str,
        amount: float,
        source_market: str,
        target_market: str,
        client_oid: str | None = None,
    ) -> dict[str, Any]:
        return self.transfer_asset(
            source_market=source_market,
            target_market=target_market,
            asset=asset,
            amount=amount,
            client_oid=client_oid,
        )

    def cancel_order(self, *, market: str, symbol: str, order_id: str) -> dict[str, Any]:
        payload = self.send(self.build_cancel_order_request(market=market, symbol=symbol, order_id=order_id))
        data = payload.get("data")
        normalized: dict[str, Any] = {
            "status": "SUCCESS" if payload.get("code") == "00000" else str(payload.get("msg", "error")).upper(),
            "exchange": self.exchange_id,
            "market": market,
            "orderId": order_id,
            "raw": payload,
        }
        if isinstance(data, dict):
            normalized.update(data)
        return normalized

    def _extract_paged_rows(self, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        data = payload.get("data")
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)], None
        if not isinstance(data, dict):
            return [], None
        for key in ("entrustedList", "fillList", "positionList", "list"):
            rows = data.get(key)
            if isinstance(rows, list):
                end_id = data.get("endId")
                return [row for row in rows if isinstance(row, dict)], str(end_id) if end_id not in (None, "") else None
        end_id = data.get("endId")
        return [], str(end_id) if end_id not in (None, "") else None

    def get_futures_order_history(
        self,
        *,
        symbol: str | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 100,
        max_pages: int = 10,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(max_pages):
            payload = self.send(
                self.build_futures_order_history_request(
                    symbol=symbol,
                    start_time_ms=start_time_ms,
                    end_time_ms=end_time_ms,
                    id_less_than=cursor,
                    limit=limit,
                )
            )
            page_rows, cursor = self._extract_paged_rows(payload)
            rows.extend(page_rows)
            if not cursor or not page_rows:
                break
        return {"orders": rows}

    def get_futures_fill_history(
        self,
        *,
        symbol: str | None = None,
        order_id: str | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 100,
        max_pages: int = 10,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(max_pages):
            payload = self.send(
                self.build_futures_fill_history_request(
                    symbol=symbol,
                    order_id=order_id,
                    start_time_ms=start_time_ms,
                    end_time_ms=end_time_ms,
                    id_less_than=cursor,
                    limit=limit,
                )
            )
            page_rows, cursor = self._extract_paged_rows(payload)
            rows.extend(page_rows)
            if not cursor or not page_rows:
                break
        return {"fills": rows}

    def get_futures_position_history(
        self,
        *,
        symbol: str | None = None,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 100,
        max_pages: int = 10,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(max_pages):
            payload = self.send(
                self.build_futures_position_history_request(
                    symbol=symbol,
                    start_time_ms=start_time_ms,
                    end_time_ms=end_time_ms,
                    id_less_than=cursor,
                    limit=limit,
                )
            )
            page_rows, cursor = self._extract_paged_rows(payload)
            rows.extend(page_rows)
            if not cursor or not page_rows:
                break
        return {"positions": rows}

    def set_futures_leverage(self, *, symbol: str, leverage: int) -> dict[str, Any]:
        payload = self.send(
            self.build_signed_request(
                path="/api/v2/mix/account/set-leverage",
                method="POST",
                body_params={
                    "symbol": symbol,
                    "productType": self.contract_config.product_type,
                    "marginCoin": self.contract_config.margin_coin,
                    "leverage": str(leverage),
                },
            )
        )
        data = payload.get("data")
        normalized: dict[str, Any] = {
            "symbol": symbol,
            "leverage": leverage,
            "raw": payload,
        }
        if isinstance(data, dict):
            normalized.update(data)
        return normalized

    def get_max_openable_quantity(
        self,
        *,
        symbol: str,
        pos_side: str,
        order_type: str = "market",
        open_amount: float | None = None,
    ) -> float | None:
        if open_amount is None:
            account = self.get_account(market="futures")
            open_amount = _optional_float(
                account.get("executionAvailableBalance", account.get("availableBalance"))
            )
        if open_amount is None or open_amount <= 0.0:
            return None
        payload = self.send(
            self.build_signed_request(
                path="/api/v2/mix/account/max-open",
                method="GET",
                params={
                    "symbol": symbol,
                    "productType": self.contract_config.product_type,
                    "marginCoin": self.contract_config.margin_coin,
                    "posSide": pos_side,
                    "orderType": order_type,
                    "openAmount": f"{open_amount:.8f}",
                },
            )
        )
        data = payload.get("data") or {}
        return _optional_float(data.get("maxOpen"))

    def get_account(self, *, market: str) -> dict[str, Any]:
        payload = self.send(self.build_account_request(market=market))
        rows = payload.get("data", [])
        if market == "futures":
            data_rows = rows if isinstance(rows, list) else []
            available: float | None = None
            crossed_max_available: float | None = None
            union_available: float | None = None
            for item in data_rows:
                if str(item.get("marginCoin", "")).upper() == self.contract_config.margin_coin.upper():
                    available = _optional_float(item.get("available"))
                    crossed_max_available = _optional_float(item.get("crossedMaxAvailable"))
                    union_available = _optional_float(item.get("unionAvailable"))
                    break
            if crossed_max_available is not None and crossed_max_available > 0:
                execution_available = crossed_max_available
            elif union_available is not None and union_available > 0:
                execution_available = min(available, union_available) if available is not None and available > 0 else union_available
            elif available is not None and available > 0:
                execution_available = available
            else:
                execution_available = union_available
            return {
                "availableBalance": available or 0.0,
                "executionAvailableBalance": execution_available or 0.0,
                "crossedMaxAvailable": crossed_max_available or 0.0,
                "unionAvailable": union_available or 0.0,
                "accounts": data_rows,
                "raw": payload,
            }
        data_rows = rows if isinstance(rows, list) else []
        balances = [
            {
                "asset": item.get("coinName") or item.get("coin"),
                "free": item.get("available"),
                "locked": item.get("frozen"),
            }
            for item in data_rows
        ]
        return {"balances": balances, "raw": payload}

    def get_open_orders(self, *, market: str, symbol: str | None = None) -> dict[str, Any]:
        payload = self.send(self.build_open_orders_request(market=market, symbol=symbol))
        return {"orders": payload.get("data", []), "raw": payload}

    def get_positions(self) -> dict[str, Any]:
        payload = self.send(self.build_positions_request())
        rows = payload.get("data", [])
        return {"positions": rows if isinstance(rows, list) else [], "raw": payload}

    def get_klines(
        self,
        *,
        market: str,
        symbol: str,
        interval: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        path = "/api/v2/mix/market/candles" if market == "futures" else "/api/v2/spot/market/candles"
        params: dict[str, Any] = {"symbol": symbol, "granularity": _bitget_granularity(market=market, interval=interval), "limit": limit}
        if market == "futures":
            params["productType"] = self.contract_config.product_type
        payload = self.send(self.build_public_request(path=path, params=params))
        rows = payload.get("data", [])
        if not isinstance(rows, list):
            raise RuntimeError("unexpected Bitget kline response shape")
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 7:
                continue
            normalized.append(
                {
                    "open_time": int(row[0]),
                    "open_price": float(row[1]),
                    "high_price": float(row[2]),
                    "low_price": float(row[3]),
                    "close_price": float(row[4]),
                    "base_volume": float(row[5]),
                    "quote_volume": float(row[6]),
                }
            )
        return normalized

    def get_book_ticker(self, *, market: str, symbol: str) -> dict[str, Any]:
        path = "/api/v2/mix/market/ticker" if market == "futures" else "/api/v2/spot/market/tickers"
        params: dict[str, Any] = {"symbol": symbol}
        if market == "futures":
            params["productType"] = self.contract_config.product_type
        payload = self.send(self.build_public_request(path=path, params=params))
        data = payload.get("data", [])
        row = data[0] if isinstance(data, list) and data else data
        if not isinstance(row, dict):
            raise RuntimeError("unexpected Bitget ticker response shape")
        return {
            "symbol": symbol,
            "bidPrice": row.get("bidPr") or row.get("bidPrice") or "0",
            "bidQty": row.get("bidSz") or row.get("bidQty") or "0",
            "askPrice": row.get("askPr") or row.get("askPrice") or "0",
            "askQty": row.get("askSz") or row.get("askQty") or "0",
            "raw": row,
        }

    def get_mark_price(self, *, symbol: str) -> dict[str, Any]:
        payload = self.send(
            self.build_public_request(
                path="/api/v2/mix/market/ticker",
                params={"symbol": symbol, "productType": self.contract_config.product_type},
            )
        )
        data = payload.get("data", [])
        row = data[0] if isinstance(data, list) and data else data
        if not isinstance(row, dict):
            raise RuntimeError("unexpected Bitget mark price response shape")
        return {
            "markPrice": row.get("markPrice") or row.get("lastPr") or "0",
            "indexPrice": row.get("indexPrice") or row.get("lastPr") or "0",
            "lastFundingRate": row.get("fundingRate") or "0",
            "raw": row,
        }

    def get_open_interest(self, *, symbol: str) -> dict[str, Any]:
        payload = self.send(
            self.build_public_request(
                path="/api/v2/mix/market/open-interest",
                params={"symbol": symbol, "productType": self.contract_config.product_type},
            )
        )
        row = payload.get("data", {})
        if not isinstance(row, dict):
            raise RuntimeError("unexpected Bitget open interest response shape")
        return {"openInterest": row.get("size") or row.get("openInterest") or "0", "raw": row}

    def get_exchange_info(self, *, market: str) -> dict[str, Any]:
        path = "/api/v2/mix/market/contracts" if market == "futures" else "/api/v2/spot/public/symbols"
        params = {"productType": self.contract_config.product_type} if market == "futures" else None
        payload = self.send(self.build_public_request(path=path, params=params))
        rows = payload.get("data", [])
        data_rows = rows if isinstance(rows, list) else []
        symbols: list[dict[str, Any]] = []
        for item in data_rows:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "")
            if not symbol:
                continue
            min_notional = item.get("minTradeUSDT") or item.get("minTradeAmount") or item.get("minTradeNum") or "0"
            min_qty = item.get("minTradeNum") or item.get("sizeMultiplier") or "0"
            filters = [
                {"filterType": "MIN_NOTIONAL", "minNotional": min_notional},
                {"filterType": "LOT_SIZE", "minQty": min_qty},
            ]
            symbols.append({"symbol": symbol, "filters": filters, "raw": item})
        return {"symbols": symbols, "raw": payload}

    def send(self, request: Request) -> dict[str, Any]:
        context = None
        if self.allow_insecure_ssl:
            context = ssl._create_unverified_context()
        try:
            with urlopen(request, timeout=10, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Bitget HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(_transport_error_message(request=request, exc=exc)) from exc
