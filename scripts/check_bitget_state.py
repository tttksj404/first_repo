"""Print current Bitget account snapshot: positions, equity, open orders."""
from __future__ import annotations

import json
import os
import sys
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

    print("=== Account ===")
    acct = client.send(client.build_account_request(market="futures"))
    if acct.get("code") == "00000":
        for row in acct.get("data") or []:
            print(f"  marginCoin={row.get('marginCoin')} available={row.get('available')} usdtEquity={row.get('usdtEquity')} unrealizedPL={row.get('unrealizedPL')} crossedRiskRate={row.get('crossedRiskRate')}")
    else:
        print(f"  ERROR: {acct}")

    print("\n=== Open positions ===")
    pos = client.send(client.build_positions_request())
    if pos.get("code") == "00000":
        positions = pos.get("data") or []
        if not positions:
            print("  (none)")
        for p in positions:
            qty = float(p.get("total") or 0)
            if qty <= 0:
                continue
            print(f"  {p.get('symbol')} {p.get('holdSide')} qty={qty} entry={p.get('openPriceAvg')} mark={p.get('markPrice')} liq={p.get('liquidationPrice')} lev={p.get('leverage')} uPL={p.get('unrealizedPL')} stopLoss={p.get('stopLoss') or '<none>'}")
    else:
        print(f"  ERROR: {pos}")

    print("\n=== Open orders ===")
    oo = client.send(client.build_open_orders_request(market="futures"))
    if oo.get("code") == "00000":
        data = oo.get("data") or {}
        rows = data.get("entrustedList") if isinstance(data, dict) else data
        if not rows:
            print("  (none)")
        else:
            print(f"  {json.dumps(rows, default=str)[:400]}")
    else:
        print(f"  ERROR: {oo}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
