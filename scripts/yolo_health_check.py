#!/usr/bin/env python3
"""한탕 모드 health check — quant_health_audit.sh에서 호출

자동 감지 + 자동 수정:
1. Spot 잔류 자금 → 선물 전송
2. Execution quality 패널티 → 리셋
3. Config 한탕 설정 검증 + 자동 수정
4. 포지션 볼륨 검증 (너무 작으면 경고)
5. Capacity 검증

Exit code:
  0 = 정상 (수정 없음)
  1 = 수정 완료 (봇 재시작 필요)
  2 = 수정 불가 (수동 개입 필요)
"""
from __future__ import annotations
import json, sys, os, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNTIME = REPO / "quant_runtime"
OVERRIDE_PATH = RUNTIME / "artifacts" / "strategy_override.approved.json"
EQ_STATE_PATH = RUNTIME / "execution_quality_state.json"

sys.path.insert(0, str(REPO))
sys.modules['quant_binance'] = type(sys)('quant_binance')
sys.modules['quant_binance'].__path__ = [str(REPO / 'quant_binance')]

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

from quant_binance.exchange import load_exchange_credentials_from_env
from quant_binance.execution.bitget_rest import BitgetRestClient

fixes_applied = 0
issues_found = 0
manual_needed = 0


def log(msg: str) -> None:
    print(f"[YOLO_HEALTH] {msg}")


def fix(msg: str) -> None:
    global fixes_applied
    fixes_applied += 1
    print(f"[YOLO_FIX] {msg}")


def issue(msg: str) -> None:
    global issues_found
    issues_found += 1
    print(f"[YOLO_ISSUE] {msg}")


def manual(msg: str) -> None:
    global manual_needed
    manual_needed += 1
    print(f"[YOLO_MANUAL] {msg}")


def check_and_fix():
    creds = load_exchange_credentials_from_env()
    client = BitgetRestClient(credentials=creds)

    # ═══════════════════════════════════════════
    # 1. Spot 잔류 자금 → 선물 전송
    # ═══════════════════════════════════════════
    log("1. Spot 잔류 자금 체크")
    spot = client.get_account(market="spot")
    for d in spot.get("raw", {}).get("data", []):
        coin = d.get("coin", "")
        avail = float(d.get("available", 0))

        if coin == "USDT" and avail > 1.0:
            try:
                client.transfer_asset(
                    source_market="spot", target_market="futures",
                    asset="USDT", amount=round(avail - 0.01, 2),
                )
                fix(f"Spot USDT ${avail:.2f} → 선물 전송")
            except Exception as e:
                issue(f"Spot USDT 전송 실패: {e}")

        elif coin in ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "LTC", "ADA", "LINK", "PEPE", "MATIC"):
            # 코인을 USDT로 매도 시도
            sym = f"{coin}USDT"
            if avail > 0:
                try:
                    params = client.build_order_params(
                        market="spot", symbol=sym, side="sell",
                        order_type="market", quantity=avail,
                    )
                    client.place_order(market="spot", order_params=params)
                    fix(f"Spot {coin} {avail} 매도 → USDT")
                    time.sleep(0.5)
                except Exception as e:
                    msg = str(e).lower()
                    if "less than" in msg or "45110" in msg or "40808" in msg or "parameter" in msg:
                        pass  # 최소주문 미달 or dust — 무시
                    else:
                        issue(f"Spot {coin} 매도 실패: {str(e)[:60]}")

    # 매도 후 USDT 전송
    time.sleep(1)
    spot2 = client.get_account(market="spot")
    for d in spot2.get("raw", {}).get("data", []):
        if d.get("coin") == "USDT":
            avail = float(d.get("available", 0))
            if avail > 1.0:
                try:
                    client.transfer_asset(
                        source_market="spot", target_market="futures",
                        asset="USDT", amount=round(avail - 0.01, 2),
                    )
                    fix(f"매도 후 USDT ${avail:.2f} → 선물 전송")
                except:
                    pass

    # ═══════════════════════════════════════════
    # 2. Execution Quality 패널티 체크 + 리셋
    # ═══════════════════════════════════════════
    log("2. Execution Quality 패널티 체크")
    if EQ_STATE_PATH.exists():
        try:
            eq = json.loads(EQ_STATE_PATH.read_text())
            has_penalty = False
            for key, overlay in (eq.get("active_overlays", eq) or {}).items():
                if isinstance(overlay, dict):
                    sz = overlay.get("size_multiplier", 1)
                    lv = overlay.get("leverage_multiplier", 1)
                    if sz < 0.9 or lv < 0.9:
                        has_penalty = True
                        issue(f"exec_quality {key}: size={sz:.2f} lev={lv:.2f}")

            if has_penalty:
                EQ_STATE_PATH.write_text("{}")
                fix("Execution quality state 리셋 (패널티 해제)")
        except:
            pass

    # ═══════════════════════════════════════════
    # 3. Strategy Override 한탕 설정 검증
    # ═══════════════════════════════════════════
    # 2b. Execution quality floor 위반 체크
    if EQ_STATE_PATH.exists():
        try:
            eq = json.loads(EQ_STATE_PATH.read_text())
            for key, overlay in (eq.get("active_overlays", eq) or {}).items():
                if isinstance(overlay, dict):
                    sz = overlay.get("size_multiplier", 1)
                    lv = overlay.get("leverage_multiplier", 1)
                    if sz < 0.85 or lv < 0.85:
                        EQ_STATE_PATH.write_text("{}")
                        fix(f"exec_quality floor 위반 (size={sz:.2f} lev={lv:.2f}) → 리셋")
                        break
        except:
            pass

    log("3. Strategy Override 설정 검증")
    if OVERRIDE_PATH.exists():
        override = json.loads(OVERRIDE_PATH.read_text())
        risk = override.get("risk", {})
        need_save = False

        required = {
            "per_trade_equity_risk": 0.15,
            "max_symbol_notional_fraction": 0.95,
            "max_total_notional_fraction": 0.95,
            "max_futures_leverage": 20.0,
            "target_futures_leverage": 15.0,
        }
        for k, min_val in required.items():
            current = risk.get(k, 0)
            if current < min_val:
                risk[k] = min_val
                need_save = True
                fix(f"{k}: {current} → {min_val}")

        # Spot 차단
        mode_th = override.get("mode_thresholds", {})
        if mode_th.get("spot_score_min", 0) < 900:
            mode_th["spot_score_min"] = 999
            mode_th["spot_liquidity_min"] = 999
            override["mode_thresholds"] = mode_th
            need_save = True
            fix("spot 진입 차단 설정")

        if need_save:
            override["risk"] = risk
            OVERRIDE_PATH.write_text(json.dumps(override, indent=2))
            fix("strategy_override.approved.json 업데이트")

    # ═══════════════════════════════════════════
    # 4. 포지션 볼륨 검증
    # ═══════════════════════════════════════════
    log("4. 포지션 볼륨 검증 + 유니버스 외 포지션 청산")
    acct = client.get_account(market="futures")
    fdata = acct.get("raw", {}).get("data", [{}])[0]
    equity = float(fdata.get("accountEquity", 0))

    # Load universe
    override_uni = set()
    if OVERRIDE_PATH.exists():
        ov = json.loads(OVERRIDE_PATH.read_text())
        override_uni = set(ov.get("universe", []))

    pos = client.get_positions()
    for p in pos.get("positions", []):
        qty = float(p.get("total", 0))
        if qty <= 0:
            continue
        sym = p.get("symbol", "?")
        side = p.get("holdSide", "long")
        mark = float(p.get("markPrice", 0))
        notional = qty * mark
        lev = int(p.get("leverage", 1))

        # Universe 밖 포지션 → 자동 청산
        if override_uni and sym not in override_uni:
            issue(f"{sym} universe 밖 포지션 — 청산 시도")
            # Cancel TP/SL first
            for pt in ["profit_loss", "normal_plan"]:
                try:
                    plans = client.get_futures_pending_plan_orders(symbol=sym, plan_type=pt)
                    for o in plans.get("orders", []):
                        try:
                            client.cancel_futures_plan_orders(
                                symbol=sym, order_id_list=[{"orderId": o["orderId"]}], plan_type=pt
                            )
                        except:
                            pass
                except:
                    pass
            time.sleep(0.5)
            # Hedge mode close: buy to close long, sell to close short
            close_side = "buy" if side == "long" else "sell"
            try:
                payload = {
                    "symbol": sym,
                    "productType": "USDT-FUTURES",
                    "marginCoin": "USDT",
                    "marginMode": "crossed",
                    "side": close_side,
                    "tradeSide": "close",
                    "orderType": "market",
                    "size": str(qty),
                    "holdSide": side,
                }
                client.place_order(market="futures", order_params=payload)
                fix(f"{sym} {side} qty={qty} 청산 완료")
            except Exception as e:
                issue(f"{sym} 청산 실패: {str(e)[:60]}")
            continue

        expected_min = equity * 0.3 * lev
        if notional < expected_min:
            issue(f"{sym} notional ${notional:.0f} < expected ${expected_min:.0f} (equity ${equity:.0f} × {lev}x × 30%)")

    # ═══════════════════════════════════════════
    # 5. Capacity 검증 (health file)
    # ═══════════════════════════════════════════
    log("5. Capacity 검증")
    health_path = RUNTIME / "live_supervisor_health.json"
    if health_path.exists():
        health = json.loads(health_path.read_text())
        if health.get("status") not in ("healthy", "starting"):
            issue(f"Bot status: {health.get('status')}")

    log(f"완료: fixes={fixes_applied} issues={issues_found} manual={manual_needed}")


if __name__ == "__main__":
    check_and_fix()
    if manual_needed > 0:
        sys.exit(2)
    elif fixes_applied > 0:
        sys.exit(1)
    else:
        sys.exit(0)
