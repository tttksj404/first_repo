"""One-shot: force-close inherited DOGEUSDT short on Bitget (hedge mode).

Reads .env from project root, queries open positions, closes DOGEUSDT short
via market order with reduce-only/close intent, then verifies position is gone.

Run from project root:
    python -m scripts.close_doge_short_oneshot
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    _load_dotenv(project_root / ".env")
    sys.path.insert(0, str(project_root))

    from quant_binance.execution.client_factory import build_exchange_rest_client

    client = build_exchange_rest_client(exchange="bitget", allow_insecure_ssl=True)

    print("[1/4] Querying open positions...")
    positions_request = client.build_positions_request()
    positions_payload = client.send(positions_request)
    if positions_payload.get("code") != "00000":
        print(f"  ERROR: positions query failed: {positions_payload}")
        return 2
    positions = positions_payload.get("data") or []
    doge_short = next(
        (p for p in positions if p.get("symbol") == "DOGEUSDT" and str(p.get("holdSide")).lower() == "short"),
        None,
    )
    if not doge_short:
        print("  No open DOGEUSDT short found. Already closed?")
        return 0
    qty = float(doge_short.get("total") or doge_short.get("available") or 0.0)
    if qty <= 0.0:
        print(f"  DOGEUSDT short found but quantity is {qty}. Nothing to close.")
        return 0
    print(f"  Found short: qty={qty}, entry={doge_short.get('openPriceAvg')}, mark={doge_short.get('markPrice')}, uPL={doge_short.get('unrealizedPL')}")

    print("[2/4] Building hedge-mode close order (BUY to close SHORT)...")
    order_params = {
        "symbol": "DOGEUSDT",
        "productType": client.contract_config.product_type,
        "marginCoin": client.contract_config.margin_coin,
        "marginMode": str(doge_short.get("marginMode") or "crossed"),
        "side": "buy",  # opposite of short closes the short
        "tradeSide": "close",
        "orderType": "market",
        "size": f"{int(qty)}",  # DOGE is integer-quantized on Bitget
        "clientOid": f"manual-close-doge-{int(time.time())}",
    }
    print(f"  Payload: {json.dumps(order_params)}")

    print("[3/4] Submitting close order...")
    result = client.place_order(market="futures", order_params=order_params)
    print(f"  Result: {json.dumps(result, default=str)[:600]}")
    if result.get("status") != "SUCCESS":
        print("  ERROR: close order rejected.")
        return 3

    print("[4/4] Verifying position closed (waiting 3s)...")
    time.sleep(3)
    positions_payload = client.send(client.build_positions_request())
    positions = positions_payload.get("data") or []
    doge_after = next(
        (p for p in positions if p.get("symbol") == "DOGEUSDT" and str(p.get("holdSide")).lower() == "short"),
        None,
    )
    if doge_after and float(doge_after.get("total") or 0) > 0:
        print(f"  WARNING: DOGEUSDT short still showing qty={doge_after.get('total')}. Manual check needed.")
        return 4
    print("  Confirmed: DOGEUSDT short is flat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
