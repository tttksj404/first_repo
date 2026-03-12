from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import ssl
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from quant_binance.exchange import ExchangeCredentials


BITGET_REST_URL = "https://api.bitget.com"
BITGET_DEFAULT_PRODUCT_TYPE = "USDT-FUTURES"
BITGET_DEFAULT_MARGIN_COIN = "USDT"


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
    _BALANCE_BACKOFF_FACTOR = 0.6
    _BALANCE_BACKOFF_MAX_ATTEMPTS = 3
    _BALANCE_BACKOFF_SLEEP_SECONDS = 0.25

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
        self._futures_symbol_size_constraints: dict[str, tuple[float, float]] | None = None

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
        payload = {
            "symbol": symbol,
            "productType": self.contract_config.product_type,
            "marginCoin": self.contract_config.margin_coin,
            "marginMode": "crossed",
            "side": side.lower(),
            "orderType": order_type.lower(),
            "size": f"{quantity:.8f}",
        }
        if reduce_only is not None:
            payload["reduceOnly"] = "YES" if reduce_only else "NO"
        if client_oid:
            payload["clientOid"] = client_oid
        return payload

    def get_futures_position_mode(self, *, symbol: str) -> str | None:
        payload = self.send(
            self.build_signed_request(
                path="/api/v2/mix/account/account",
                method="GET",
                params={
                    "symbol": symbol,
                    "productType": self.contract_config.product_type,
                    "marginCoin": self.contract_config.margin_coin,
                },
            )
        )
        data = payload.get("data", {})
        if isinstance(data, dict):
            mode = data.get("posMode")
            if isinstance(mode, str) and mode:
                return mode
        return None

    def _normalize_futures_order_params_for_position_mode(self, params: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(params)
        side = str(normalized.get("side", "")).lower()
        is_buy = side in {"buy", "buy_single", "open_long"}
        normalized["side"] = "buy" if is_buy else "sell"
        symbol = str(normalized.get("symbol", "")).upper()
        if not symbol:
            return normalized
        try:
            pos_mode = self.get_futures_position_mode(symbol=symbol)
        except Exception:
            pos_mode = None
        if pos_mode == "hedge_mode":
            normalized["tradeSide"] = str(normalized.get("tradeSide", "open")).lower()
            normalized.pop("reduceOnly", None)
            normalized.pop("holdSide", None)
        elif pos_mode == "one_way_mode":
            normalized.pop("tradeSide", None)
            normalized["reduceOnly"] = str(normalized.get("reduceOnly", "NO")).upper()
            normalized.pop("holdSide", None)
        return normalized

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _decimal_places(step: float) -> int:
        if step <= 0:
            return 8
        text = f"{step:.12f}".rstrip("0")
        if "." not in text:
            return 0
        return min(len(text.split(".")[1]), 8)

    def _load_futures_symbol_size_constraints(self) -> dict[str, tuple[float, float]]:
        if self._futures_symbol_size_constraints is not None:
            return self._futures_symbol_size_constraints
        info = self.get_exchange_info(market="futures")
        constraints: dict[str, tuple[float, float]] = {}
        for item in info.get("symbols", []):
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "")).upper()
            raw = item.get("raw", {})
            if not symbol or not isinstance(raw, dict):
                continue
            min_size = self._safe_float(raw.get("minTradeNum") or raw.get("minTradeAmount") or 0.0)
            size_step = self._safe_float(raw.get("sizeMultiplier") or 0.0)
            constraints[symbol] = (min_size, size_step)
        self._futures_symbol_size_constraints = constraints
        return constraints

    def _normalize_futures_size(self, *, symbol: str, size: float) -> float:
        normalized = max(float(size), 0.0)
        constraints = self._load_futures_symbol_size_constraints()
        min_size, size_step = constraints.get(symbol.upper(), (0.0, 0.0))
        if size_step > 0:
            normalized = math.floor((normalized + 1e-12) / size_step) * size_step
            normalized = round(normalized, self._decimal_places(size_step))
        else:
            normalized = round(normalized, 8)
        if min_size > 0 and normalized < min_size:
            return 0.0
        return normalized

    def test_order(self, *, market: str, order_params: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "PREVIEW",
            "exchange": self.exchange_id,
            "market": market,
            "request": dict(order_params),
            "note": "Bitget has no Binance-style order/test REST endpoint; this first pass performs local payload preview only.",
        }

    def place_order(self, *, market: str, order_params: dict[str, Any]) -> dict[str, Any]:
        def _send(params: dict[str, Any]) -> dict[str, Any]:
            return self.send(self.build_live_order_request(market=market, order_params=params))

        def _with_balance_backoff(params: dict[str, Any]) -> dict[str, Any]:
            if market != "futures":
                return _send(params)
            current = dict(params)
            last_error: RuntimeError | None = None
            for attempt in range(self._BALANCE_BACKOFF_MAX_ATTEMPTS):
                try:
                    return _send(current)
                except RuntimeError as exc:
                    if "code=40762" not in str(exc):
                        raise
                    last_error = exc
                    symbol = str(current.get("symbol", "")).upper()
                    try:
                        size = float(current.get("size", 0.0))
                    except (TypeError, ValueError):
                        break
                    if size <= 0:
                        break
                    reduced_size = size * self._BALANCE_BACKOFF_FACTOR
                    if symbol:
                        reduced_size = self._normalize_futures_size(symbol=symbol, size=reduced_size)
                    else:
                        reduced_size = round(reduced_size, 8)
                    if reduced_size <= 0 or reduced_size >= size:
                        break
                    current["size"] = f"{reduced_size:.8f}"
                    if attempt + 1 < self._BALANCE_BACKOFF_MAX_ATTEMPTS:
                        time.sleep(self._BALANCE_BACKOFF_SLEEP_SECONDS * (attempt + 1))
            if last_error is not None:
                raise last_error
            return _send(current)

        initial_params = dict(order_params)
        if market == "futures":
            initial_params = self._normalize_futures_order_params_for_position_mode(initial_params)
            symbol = str(initial_params.get("symbol", "")).upper()
            size = self._safe_float(initial_params.get("size"))
            if symbol and size > 0:
                normalized_size = self._normalize_futures_size(symbol=symbol, size=size)
                if normalized_size <= 0:
                    raise RuntimeError(
                        f"Bitget preflight rejected futures order for {symbol}: code=45111 msg=less than the minimum order quantity"
                    )
                initial_params["size"] = f"{normalized_size:.8f}"
        try:
            payload = _with_balance_backoff(initial_params)
        except RuntimeError as exc:
            if market != "futures":
                raise
            raw_msg = str(exc)
            side = str(initial_params.get("side", "")).lower()
            is_buy = side in {"buy", "buy_single", "open_long"}
            hedge_side = "buy" if is_buy else "sell"
            one_way_side = "buy_single" if is_buy else "sell_single"
            legacy_open_side = "open_long" if is_buy else "open_short"
            hold_side = "long" if is_buy else "short"

            retry_candidates: list[dict[str, Any]] = []
            if "code=40774" in raw_msg:
                retry_candidates.append({**initial_params, "side": one_way_side})
                retry_candidates[-1].pop("tradeSide", None)
                retry_candidates.append({**initial_params, "side": legacy_open_side, "holdSide": hold_side})
            elif "code=400172" in raw_msg:
                retry_candidates.append({**initial_params, "side": hedge_side, "tradeSide": "open"})
                retry_candidates.append({**initial_params, "side": one_way_side})
                retry_candidates[-1].pop("tradeSide", None)
                retry_candidates.append({**initial_params, "side": legacy_open_side, "holdSide": hold_side})
            else:
                raise

            last_error: RuntimeError = exc
            for candidate in retry_candidates:
                try:
                    payload = _with_balance_backoff(candidate)
                    break
                except RuntimeError as retry_exc:
                    last_error = retry_exc
            else:
                raise last_error
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

    def get_account(self, *, market: str) -> dict[str, Any]:
        payload = self.send(self.build_account_request(market=market))
        rows = payload.get("data", [])
        if market == "futures":
            data_rows = rows if isinstance(rows, list) else []
            available = 0.0
            raw_available = 0.0
            crossed_max_available = 0.0
            union_available = 0.0
            has_crossed_max_available = False
            for item in data_rows:
                if str(item.get("marginCoin", "")).upper() == self.contract_config.margin_coin.upper():
                    raw_available = float(item.get("available", 0.0))
                    has_crossed_max_available = "crossedMaxAvailable" in item
                    crossed_max_available = float(item.get("crossedMaxAvailable", 0.0))
                    union_available = float(item.get("unionAvailable", 0.0))
                    available = raw_available
                    break
            if has_crossed_max_available and crossed_max_available > 0:
                effective_available = crossed_max_available
            else:
                effective_candidates = [value for value in (raw_available, union_available) if value > 0]
                effective_available = min(effective_candidates) if effective_candidates else available
            return {
                "availableBalance": available,
                "effectiveAvailableBalance": effective_available,
                "rawAvailableBalance": raw_available,
                "crossedMaxAvailable": crossed_max_available,
                "unionAvailable": union_available,
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

    def get_klines(
        self,
        *,
        market: str,
        symbol: str,
        interval: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        granularity = interval
        if market == "spot":
            if interval.endswith("m"):
                granularity = f"{interval[:-1]}min"
        else:
            if interval.endswith("h"):
                granularity = f"{interval[:-1]}H"
            elif interval.endswith("d"):
                granularity = f"{interval[:-1]}D"
        path = "/api/v2/mix/market/candles" if market == "futures" else "/api/v2/spot/market/candles"
        params: dict[str, Any] = {"symbol": symbol, "granularity": granularity, "limit": limit}
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
            filters = [{"filterType": "MIN_NOTIONAL", "minNotional": min_notional}]
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
            raw = exc.read().decode("utf-8", errors="ignore")
            detail = raw
            try:
                payload = json.loads(raw) if raw else {}
                if isinstance(payload, dict):
                    compact_raw = raw.replace("\n", " ").strip()
                    detail = f"code={payload.get('code')} msg={payload.get('msg')} raw={compact_raw}"
            except Exception:
                pass
            raise RuntimeError(
                f"Bitget HTTP {exc.code} {exc.reason} for {request.get_method()} {request.full_url}: {detail}"
            ) from exc
