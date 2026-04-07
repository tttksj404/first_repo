# /order-flow — 주문 생애주기 관리 검증

부분체결, 취소, 재연결 후 고아 주문 등 주문 상태 전이를 올바르게 처리하는지 검증합니다.
실거래에서 가장 많이 발생하는 예외 상황들.

## 사용법

```
/order-flow                      # 주문 처리 로직 전체 검토
/order-flow --audit              # 현재 미결 주문 전수 감사
/order-flow --reconcile          # 거래소 vs 로컬 상태 대조
```

## 주문 상태 전이도

```
생성 요청
    ↓
PENDING_SUBMIT
    ↓
SUBMITTED ──────────── API 에러 → ERROR (재시도 or 취소)
    ↓
OPEN ────────────────── 타임아웃 → CANCEL_PENDING → CANCELLED
    ↓                              ↑
PARTIALLY_FILLED ─────────────────┘ (부분체결 후 취소)
    ↓
FILLED (완전 체결)
```

## 핵심 검증 항목

### 1. 부분체결 처리
```python
# ❌ 흔한 실수 — 체결 여부만 확인
if order['status'] == 'closed':
    update_position(order['amount'])  # 부분체결 시 amount ≠ filled

# ✅ 올바른 처리
if order['status'] in ('closed', 'canceled'):
    filled_amount = order['filled']   # 실제 체결량 사용
    remaining = order['amount'] - order['filled']
    update_position(filled_amount)
    if remaining > 0:
        log.warning(f"미체결 수량: {remaining}")
```

### 2. 고아 주문 (Orphan Orders) 방지
```python
# 봇 재시작 시 미결 주문 복구
def on_startup():
    open_orders = exchange.fetch_open_orders()
    for order in open_orders:
        if order['id'] not in local_order_registry:
            # 봇 재시작 전 생성된 주문
            handle_orphan_order(order)  # 취소 or 로컬 등록

# 취소 확인까지 대기 (즉각 반환 X)
def cancel_order_with_confirm(order_id, timeout=10):
    exchange.cancel_order(order_id)
    start = time.time()
    while time.time() - start < timeout:
        order = exchange.fetch_order(order_id)
        if order['status'] == 'canceled':
            return True
        time.sleep(0.5)
    raise Exception(f"주문 취소 확인 실패: {order_id}")
```

### 3. API 에러별 재시도 전략
```python
RETRY_STRATEGY = {
    'NetworkError'    : {'retry': True,  'max': 3, 'delay': 1.0},
    'RateLimitError'  : {'retry': True,  'max': 5, 'delay': 60.0},
    'InsufficientFunds': {'retry': False},  # 재시도 무의미
    'InvalidOrder'    : {'retry': False},  # 파라미터 오류
    'OrderNotFound'   : {'retry': False},  # 이미 처리됨
    'ExchangeError'   : {'retry': True,  'max': 2, 'delay': 5.0},
}
```

### 4. 거래소 ↔ 로컬 상태 대조
```python
def reconcile():
    exchange_orders = exchange.fetch_open_orders()
    local_orders    = load_local_order_registry()

    # 거래소에 있지만 로컬에 없는 주문 (고아)
    orphans = [o for o in exchange_orders if o['id'] not in local_orders]

    # 로컬에 OPEN이지만 거래소에서 이미 체결/취소
    stale = [id for id, o in local_orders.items()
             if o['status'] == 'open'
             and id not in [eo['id'] for eo in exchange_orders]]

    return orphans, stale
```

### 5. OCO (One Cancels Other) 주문 처리
```python
# TP 체결 시 SL 자동 취소 (거래소에서 안 해주는 경우)
def on_order_filled(order):
    if order['id'] == tp_order_id:
        cancel_order_with_confirm(sl_order_id)
    elif order['id'] == sl_order_id:
        cancel_order_with_confirm(tp_order_id)
```

## 출력 형식

```
ORDER FLOW AUDIT — 2026-03-27
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
부분체결 처리  : ✅ filled 필드 사용
고아 주문 방지 : ❌ 재시작 시 open_orders 미확인
취소 확인 대기 : ⚠️ 즉시 반환 (비동기 취소 위험)
에러 재시도    : ✅ 타입별 분리됨
상태 대조      : ❌ reconcile 함수 없음
OCO 처리       : ✅ 상호 취소 구현됨
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
현재 미결 주문 : 2건 (모두 로컬 등록됨)
고아 주문      : 없음
수정 필요      : 재시작 복구 로직 + 취소 확인 대기
```
