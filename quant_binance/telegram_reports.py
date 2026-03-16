from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_latest_jsonl_record(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    for raw in reversed(path.read_text(encoding="utf-8").splitlines()):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def format_runtime_telegram_report(
    base_dir: str | Path = "quant_runtime",
    *,
    event: str = "",
    metadata: dict[str, str] | None = None,
) -> str:
    base = Path(base_dir)
    latest = base / "output" / "paper-live-shell" / "latest"
    summary = _load_json(latest / "summary.json")
    state = _load_json(latest / "summary.state.json")
    overview = _load_json(latest / "overview.json")
    health = _load_json(base / "live_supervisor_health.json")
    latest_order_error = _load_latest_jsonl_record(latest / "logs" / "order_errors.jsonl")
    latest_live_order = _load_latest_jsonl_record(latest / "logs" / "live_orders.jsonl")
    latest_closed_trade = _load_latest_jsonl_record(latest / "logs" / "closed_trades.jsonl")
    meta = metadata or {}

    event_label_map = {
        "started": "시작",
        "stopped": "중지",
        "unhealthy": "이상 감지",
        "exited": "재시작/종료",
    }
    title = "[오픈클로 실거래 요약 리포트]"
    if event:
        title = f"{title} {event_label_map.get(event, event)}"

    self_healing = summary.get("self_healing") or state.get("self_healing") or {}
    recent_events = self_healing.get("recent_events") or []
    positions = summary.get("exchange_live_futures_positions") or summary.get("live_positions") or []
    recent_live_orders = summary.get("live_orders") or []
    open_orders_snapshot = summary.get("open_orders_snapshot") or {}
    orders = open_orders_snapshot.get("orders") if isinstance(open_orders_snapshot, dict) else {}
    entrusted = []
    if isinstance(orders, dict):
        entrusted = orders.get("entrustedList") or orders.get("list") or []
    elif isinstance(orders, list):
        entrusted = orders

    lines = [
        title,
        f"업데이트 시각: {overview.get('updated_at') or state.get('updated_at') or '없음'}",
        f"헬스 상태: {health.get('status') or overview.get('status') or 'unknown'}",
        f"의사결정 수: {summary.get('decision_count', state.get('decision_count', 0))}",
        f"실주문 수: {summary.get('live_order_count', state.get('live_order_count', 0))}",
        f"테스트 주문 수: {summary.get('tested_order_count', state.get('tested_order_count', 0))}",
        f"미체결 주문 수: {len(entrusted)}",
        f"거래소 실포지션 수: {len(positions)}",
    ]

    if meta.get("reason"):
        lines.append(f"이벤트 사유: {meta['reason']}")
    if meta.get("exit_code"):
        lines.append(f"종료 코드: {meta['exit_code']}")

    if positions:
        lines.append("보유 포지션:")
        for item in positions[:5]:
            unrealized = float(item.get("unrealizedPL") or item.get("unrealized_pnl_usd") or 0.0)
            lines.append(
                f"- {item.get('symbol')} {item.get('holdSide') or item.get('side')} "
                f"미실현={unrealized:.4f}"
            )

    if recent_live_orders:
        lines.append("최근 체결 주문:")
        for item in recent_live_orders[-3:]:
            lines.append(
                f"- {item.get('symbol')} {item.get('side')} qty={item.get('quantity')} "
                f"accepted={item.get('accepted')} orderId={item.get('order_id')}"
            )
    elif latest_live_order:
        lines.append(
            "최근 체결 주문: "
            f"{latest_live_order.get('symbol')} {latest_live_order.get('side')} "
            f"qty={latest_live_order.get('quantity')} orderId={latest_live_order.get('order_id')}"
        )

    if latest_closed_trade:
        pnl = float(latest_closed_trade.get("realized_pnl_usd_estimate", 0.0))
        lines.append(
            "최근 종료 거래: "
            f"{latest_closed_trade.get('symbol')} {latest_closed_trade.get('exit_reason')} pnl={pnl:.4f}"
        )

    if latest_order_error:
        error_text = str(
            latest_order_error.get("error")
            or latest_order_error.get("error_message")
            or ""
        )
        lines.append(
            "최근 주문 이슈: "
            f"{latest_order_error.get('symbol')} {latest_order_error.get('stage')} {error_text[:160]}"
        )

    if recent_events:
        latest_event = recent_events[-1]
        lines.append(
            "자동복구 상태: "
            f"{latest_event.get('category')} / {latest_event.get('automatic_action')} / {latest_event.get('status')}"
        )

    top_rejections = summary.get("top_rejection_reasons") or {}
    if top_rejections:
        rows = [f"{key}:{value}" for key, value in list(top_rejections.items())[:4]]
        lines.append("주요 거절 사유: " + ", ".join(rows))

    return "\n".join(lines)


def format_weekly_validation_report(base_dir: str | Path = "quant_runtime") -> str:
    path = Path(base_dir) / "artifacts" / "weekly_validation_report.json"
    payload = _load_json(path)
    if not payload:
        return "주간 검증 리포트가 아직 없습니다."
    lines = [
        "[주간 검증 리포트]",
        f"최근 run 수: {payload.get('run_count', 0)}",
        f"실현 거래 수: {payload.get('total_closed_trade_count', 0)}",
        f"실현 손익(USD): {float(payload.get('total_realized_pnl_usd', 0.0)):.4f}",
        f"실주문 수: {payload.get('total_live_order_count', 0)}",
        f"테스트 주문 수: {payload.get('total_tested_order_count', 0)}",
    ]
    regime_rows = payload.get("regime_summary") or []
    if regime_rows:
        lines.append("레짐별 요약:")
        for row in regime_rows[:4]:
            lines.append(
                f"- {row.get('mode')}: decision={row.get('decision_count')} "
                f"avg_score={float(row.get('avg_score', 0.0)):.2f} "
                f"avg_edge={float(row.get('avg_net_edge_bps', 0.0)):.2f}bps"
            )
    symbol_rows = payload.get("symbol_summary") or []
    if symbol_rows:
        promote = [row for row in symbol_rows if row.get("recommendation") == "promote"][:3]
        prune = [row for row in symbol_rows if row.get("recommendation") in {"prune", "observe_only"}][:3]
        if promote:
            lines.append("승격 후보:")
            for row in promote:
                lines.append(
                    f"- {row.get('symbol')}: expectancy={float(row.get('expectancy_usd', 0.0)):.4f}, "
                    f"pnl={float(row.get('realized_pnl_usd', 0.0)):.4f}"
                )
        if prune:
            lines.append("제외/관찰 후보:")
            for row in prune:
                lines.append(
                    f"- {row.get('symbol')}: {row.get('recommendation')} "
                    f"(expectancy={float(row.get('expectancy_usd', 0.0)):.4f})"
                )
    return "\n".join(lines)


def format_execution_quality_report(base_dir: str | Path = "quant_runtime") -> str:
    path = Path(base_dir) / "artifacts" / "execution_quality_report.json"
    payload = _load_json(path)
    if not payload:
        return "실행 품질 리포트가 아직 없습니다."
    lines = [
        "[실행 품질 리포트]",
        f"최근 run 수: {payload.get('run_count', 0)}",
        f"실주문 수: {payload.get('live_order_count', 0)}",
        f"실주문 성공 추정 수: {payload.get('accepted_live_order_count', 0)}",
        f"실주문 성공률 추정: {float(payload.get('estimated_live_acceptance_rate', 0.0)) * 100:.2f}%",
        f"테스트 주문 수: {payload.get('tested_order_count', 0)}",
        f"주문 오류 수: {payload.get('order_error_count', 0)}",
    ]
    top_error_codes = payload.get("top_error_codes") or []
    if top_error_codes:
        lines.append("주요 오류 코드:")
        for row in top_error_codes[:5]:
            lines.append(f"- code={row.get('code')} count={row.get('count')}")
    symbol_rows = payload.get("symbol_order_summary") or []
    if symbol_rows:
        lines.append("심볼별 주문 상태:")
        for row in symbol_rows[:5]:
            lines.append(
                f"- {row.get('symbol')}: live={row.get('live_order_count')} "
                f"accept_rate={float(row.get('estimated_live_acceptance_rate', 0.0)) * 100:.1f}% "
                f"errors={row.get('order_error_count')}"
            )
    return "\n".join(lines)
