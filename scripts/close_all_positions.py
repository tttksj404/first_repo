#!/usr/bin/env python3
"""전 포지션 청산 + 대기주문 취소 — 안전 배포용

사용법:
  python3 scripts/close_all_positions.py          # 조회만 (dry-run)
  python3 scripts/close_all_positions.py --execute # 실제 청산
"""
from __future__ import annotations

import sys
import time

import os, sys
# Direct import to avoid heavy __init__.py chain
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from quant_binance.exchange import load_exchange_credentials_from_env
from quant_binance.execution.bitget_rest import BitgetRestClient


def main():
    execute = "--execute" in sys.argv

    creds = load_exchange_credentials_from_env()
    client = BitgetRestClient(credentials=creds)

    print("=" * 60)
    print("포지션 청산 스크립트" + (" [EXECUTE MODE]" if execute else " [DRY-RUN]"))
    print("=" * 60)

    # 1. 열린 포지션 조회
    print("\n[1/3] 열린 포지션 조회...")
    pos_result = client.get_positions()
    positions = pos_result.get("positions", [])

    open_positions = [p for p in positions if float(p.get("total", 0)) > 0]

    if not open_positions:
        print("  열린 포지션 없음")
    else:
        for p in open_positions:
            sym = p.get("symbol", "?")
            side = p.get("holdSide", "?")
            qty = p.get("total", "0")
            pnl = p.get("unrealizedPL", "0")
            lev = p.get("leverage", "?")
            print(f"  {sym} {side} qty={qty} leverage={lev}x PnL=${float(pnl):.2f}")

    # 2. 대기 중 TP/SL plan orders 조회 + 취소
    print("\n[2/3] 대기 중 plan orders (TP/SL) 조회...")
    try:
        plan_result = client.get_futures_pending_plan_orders()
        plan_orders = plan_result.get("orders", [])
    except Exception as e:
        print(f"  plan orders 조회 실패: {e}")
        plan_orders = []

    if not plan_orders:
        print("  대기 plan orders 없음")
    else:
        for o in plan_orders:
            sym = o.get("symbol", "?")
            oid = o.get("orderId", "?")
            plan_type = o.get("planType", "?")
            print(f"  {sym} orderId={oid} type={plan_type}")

        if execute:
            # 심볼별로 그룹핑해서 취소
            by_symbol: dict[str, list[dict]] = {}
            for o in plan_orders:
                sym = o.get("symbol", "")
                if sym:
                    by_symbol.setdefault(sym, []).append(o)

            for sym, orders in by_symbol.items():
                order_id_list = [{"orderId": o["orderId"]} for o in orders if o.get("orderId")]
                if order_id_list:
                    try:
                        result = client.cancel_futures_plan_orders(
                            symbol=sym,
                            order_id_list=order_id_list,
                        )
                        print(f"  {sym}: {len(order_id_list)}개 plan order 취소 → {result.get('status', '?')}")
                    except Exception as e:
                        print(f"  {sym}: plan order 취소 실패: {e}")

    # 3. 포지션 청산 (마켓 주문으로 close)
    print("\n[3/3] 포지션 청산...")
    if not open_positions:
        print("  청산할 포지션 없음")
    elif not execute:
        print("  DRY-RUN: --execute 옵션 추가하면 실제 청산 실행")
        for p in open_positions:
            sym = p.get("symbol", "?")
            side = p.get("holdSide", "?")
            qty = float(p.get("total", 0))
            close_side = "sell" if side == "long" else "buy"
            print(f"  → {sym}: {close_side} {qty} (reduce_only, tradeSide=close)")
    else:
        for p in open_positions:
            sym = p.get("symbol", "?")
            side = p.get("holdSide", "?")
            qty = float(p.get("total", 0))
            close_side = "sell" if side == "long" else "buy"

            try:
                params = client.build_order_params(
                    market="futures",
                    symbol=sym,
                    side=close_side,
                    order_type="market",
                    quantity=qty,
                    reduce_only=True,
                )
                result = client.place_order(market="futures", order_params=params)
                status = result.get("status", "?")
                print(f"  {sym} {side} qty={qty} → {close_side} → {status}")
            except Exception as e:
                print(f"  {sym} 청산 실패: {e}")
            time.sleep(0.3)

    # 4. 최종 확인
    if execute:
        print("\n[확인] 잔여 포지션 체크...")
        time.sleep(1)
        pos_result2 = client.get_positions()
        remaining = [p for p in pos_result2.get("positions", []) if float(p.get("total", 0)) > 0]
        if remaining:
            print(f"  경고: {len(remaining)}개 포지션 미청산")
            for p in remaining:
                print(f"    {p.get('symbol')} {p.get('holdSide')} qty={p.get('total')}")
        else:
            print("  전 포지션 청산 완료")

    print("\n" + "=" * 60)
    print("완료" + (" — 실제 청산됨" if execute else " — DRY-RUN (--execute로 실행)"))
    print("=" * 60)


if __name__ == "__main__":
    main()
