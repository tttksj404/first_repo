"""
quant_bug_detector.py — 런타임 버그/에러 패턴 자동 감지
========================================================
health audit에서 호출. 감지된 이슈를 JSON으로 출력.
Claude가 읽고 자동 수정할 수 있도록 구체적인 진단 정보 포함.

감지 카테고리 (20종):
  A. API/네트워크
    1. repeated_api_error      — 동일 API 에러 반복 (TRAILING_STOP, TPSL 등)
    2. dns_resolution_failed   — DNS 해석 실패 (인터넷 끊김)
    3. transport_exhausted     — REST 재시도 한계 초과
    4. rate_limited            — Bitget 429 rate limit
    5. websocket_unstable      — WS 재연결 반복
  B. 주문/포지션
    6. rapid_exit              — 너무 빠른 청산 (10분 내 2회+)
    7. exit_cascade            — 10분 내 exit 3회+ 연쇄 발동
    8. fee_eating_profit       — 수수료가 수익의 50%+
    9. order_rejected          — 주문 거부 (잔고 부족, 최소금액 등)
    10. coin_convert_loop      — 코인 변환 무한 반복 (최소금액 미달)
    11. position_mismatch      — paper vs exchange 포지션 불일치
    12. stale_position         — 최대 보유시간 초과
  C. 전략/의사결정
    13. high_rejection_rate    — 진입 거부율 95%+
    14. zero_decisions         — 의사결정 0건 (데몬 stall)
    15. all_losses             — 최근 N건 전부 손실
  D. 시스템
    16. trailing_stop_failures — 트레일링 스탑 실패율 50%+
    17. equity_declining       — equity 지속 하락
    18. stall_recovery         — STALL_RECOVERY 발동
    19. memory_leak            — 메모리 지속 증가
    20. config_mismatch        — override 설정값 이상

Exit codes:
  0 = 이슈 없음
  1 = WARNING 이슈 발견
  2 = CRITICAL 이슈 발견
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

RUNTIME = Path("/Users/tttksj/first_repo/quant_runtime")
REPO = Path("/Users/tttksj/first_repo")


# ═══════════════════════════════════════════════════════════════
# 데이터 로더
# ═══════════════════════════════════════════════════════════════

def _find_current_session_start(lines: list[str]) -> int:
    """현재 데몬 세션 시작 위치 찾기 (마지막 'daemon.*restored' 또는 'daemon.*equity')."""
    for i in range(len(lines) - 1, -1, -1):
        if "[daemon]" in lines[i] and ("restored" in lines[i] or "equity auto-detected" in lines[i]):
            return i
    return 0


def _read_recent_daemon_log(max_lines: int = 5000) -> list[str]:
    log = RUNTIME / "daemon_restart.log"
    if not log.exists():
        return []
    lines = log.read_text(errors="replace").splitlines()
    recent = lines[-max_lines:]
    # 현재 세션만 반환 (이전 세션의 에러를 현재 에러로 오인 방지)
    session_start = _find_current_session_start(recent)
    return recent[session_start:]


def _read_all_daemon_log(max_lines: int = 5000) -> list[str]:
    """세션 구분 없이 전체 최근 로그 (equity trend 등에 사용)."""
    log = RUNTIME / "daemon_restart.log"
    if not log.exists():
        return []
    lines = log.read_text(errors="replace").splitlines()
    return lines[-max_lines:]


def _read_supervisor_log(max_lines: int = 2000) -> list[str]:
    log = RUNTIME / "live_supervisor.log"
    if not log.exists():
        return []
    lines = log.read_text(errors="replace").splitlines()
    return lines[-max_lines:]


def _read_closed_trades() -> list[dict]:
    base = RUNTIME / "output" / "paper-live-shell"
    if not base.exists():
        return []
    sessions = sorted(
        [d for d in base.iterdir() if d.is_dir() and d.name != "latest"],
        reverse=True,
    )
    trades = []
    for session_dir in sessions[:3]:
        ct = session_dir / "logs" / "closed_trades.jsonl"
        if ct.exists():
            for line in ct.read_text(errors="replace").splitlines():
                try:
                    trades.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return trades


def _read_position_actions() -> list[dict]:
    base = RUNTIME / "output" / "paper-live-shell"
    if not base.exists():
        return []
    sessions = sorted(
        [d for d in base.iterdir() if d.is_dir() and d.name != "latest"],
        reverse=True,
    )
    actions = []
    for session_dir in sessions[:2]:
        pa = session_dir / "logs" / "live_position_actions.jsonl"
        if pa.exists():
            for line in pa.read_text(errors="replace").splitlines():
                try:
                    actions.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return actions


def _read_account_sync() -> list[dict]:
    base = RUNTIME / "output" / "paper-live-shell"
    if not base.exists():
        return []
    sessions = sorted(
        [d for d in base.iterdir() if d.is_dir() and d.name != "latest"],
        reverse=True,
    )
    syncs = []
    for session_dir in sessions[:1]:
        sf = session_dir / "logs" / "account_sync.jsonl"
        if sf.exists():
            for line in sf.read_text(errors="replace").splitlines():
                try:
                    syncs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return syncs


def _read_override() -> dict:
    p = RUNTIME / "artifacts" / "strategy_override.approved.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    return {}


# ═══════════════════════════════════════════════════════════════
# A. API/네트워크 체크
# ═══════════════════════════════════════════════════════════════

def check_repeated_api_errors(lines: list[str]) -> list[dict]:
    """동일 API 에러 반복 감지."""
    issues = []
    error_patterns: dict[str, list[str]] = defaultdict(list)

    for line in lines:
        if "update failed:" in line or "HTTP 4" in line or "HTTP 5" in line:
            m = re.search(r'\[(\w+)\].*(?:failed|HTTP \d+).*?(?:code.*?"(\d+)".*?msg.*?"([^"]+)")?', line)
            if m:
                component = m.group(1)
                code = m.group(2) or "unknown"
                msg = m.group(3) or line[:100]
                key = f"{component}:{code}"
                error_patterns[key].append(msg)

    for key, msgs in error_patterns.items():
        count = len(msgs)
        if count >= 5:
            severity = "CRITICAL" if count >= 15 else "WARNING"
            issues.append({
                "type": "repeated_api_error",
                "severity": severity,
                "component": key.split(":")[0],
                "error_code": key.split(":")[1],
                "count": count,
                "sample_message": msgs[0][:200],
                "diagnosis": f"{key} 에러 {count}회 반복 — 코드 버그 또는 API 파라미터 오류",
                "fix_hint": f"quant_binance/ 에서 {key.split(':')[0]} 관련 코드 확인. "
                            f"에러 메시지: {msgs[0][:100]}",
            })
    return issues


def check_dns_failure(lines: list[str]) -> list[dict]:
    """DNS 해석 실패 (인터넷 끊김)."""
    issues = []
    dns_errors = [l for l in lines if "DNS resolution" in l or "nodename nor servname" in l]
    if len(dns_errors) >= 5:
        issues.append({
            "type": "dns_resolution_failed",
            "severity": "CRITICAL",
            "count": len(dns_errors),
            "diagnosis": f"DNS 해석 실패 {len(dns_errors)}회 — 인터넷 연결 끊김 또는 DNS 서버 문제",
            "fix_hint": "1) 인터넷 연결 확인 (ping api.bitget.com) "
                        "2) DNS 서버 변경 (8.8.8.8) "
                        "3) VPN 상태 확인 "
                        "4) 일시적이면 데몬이 자동 복구함 — 30분+ 지속되면 수동 개입",
        })
    return issues


def check_transport_exhausted(lines: list[str]) -> list[dict]:
    """REST 재시도 한계 초과."""
    issues = []
    stall_lines = [l for l in lines if "STALL_RECOVERY_LIMIT_EXCEEDED" in l]
    transport_lines = [l for l in lines if "transport error (exhausted retries)" in l]
    total = len(stall_lines) + len(transport_lines)
    if total >= 1:
        issues.append({
            "type": "transport_exhausted",
            "severity": "CRITICAL",
            "stall_count": len(stall_lines),
            "transport_count": len(transport_lines),
            "diagnosis": f"REST 재시도 한계 초과 {total}회 — 데몬 재시작 필요할 수 있음",
            "fix_hint": "self_healing이 자동 재시작 시도함. "
                        "반복되면 Bitget API 점검 또는 네트워크 문제. "
                        "데몬 프로세스 확인: pgrep -f quant_binance",
        })
    return issues


def check_rate_limited(lines: list[str]) -> list[dict]:
    """Bitget 429 rate limit."""
    issues = []
    rate_lines = [l for l in lines if "429" in l or "rate_limit" in l.lower() or "rate limit" in l.lower()]
    if len(rate_lines) >= 10:
        issues.append({
            "type": "rate_limited",
            "severity": "WARNING",
            "count": len(rate_lines),
            "diagnosis": f"API rate limit {len(rate_lines)}회 — 요청 빈도 초과",
            "fix_hint": "sync_interval_seconds 늘리기 (현재 15초). "
                        "trailing_stop 업데이트 빈도 줄이기 (_TRAILING_MIN_MOVE_BPS 올리기). "
                        "불필요한 RECONCILE_POSITION_TPSL 줄이기.",
        })
    return issues


def check_websocket_stability(lines: list[str]) -> list[dict]:
    """웹소켓 연결 안정성."""
    issues = []
    errors = [l for l in lines if "[ERROR]" in l and "websocket" in l]
    # DNS 에러와 일반 WS 에러 분리
    dns_ws = [l for l in errors if "nodename" in l or "DNS" in l]
    normal_ws = [l for l in errors if "no close frame" in l]

    if len(dns_ws) >= 10:
        issues.append({
            "type": "websocket_dns_failure",
            "severity": "CRITICAL",
            "count": len(dns_ws),
            "diagnosis": f"웹소켓 DNS 실패 {len(dns_ws)}회 — 인터넷 끊김 상태에서 WS 재연결 시도 중",
            "fix_hint": "인터넷 연결 복구 필요. REST fallback은 작동하나 실시간성 없음.",
        })
    elif len(normal_ws) >= 20:
        issues.append({
            "type": "websocket_unstable",
            "severity": "WARNING",
            "count": len(normal_ws),
            "diagnosis": f"웹소켓 'no close frame' {len(normal_ws)}회. Bitget WS 특성상 정상 범위일 수 있음.",
            "fix_hint": "REST sync가 60초마다 정상 작동 중이면 무시 가능. "
                        "SYNC 로그가 끊겼다면 데몬 재시작.",
        })
    return issues


# ═══════════════════════════════════════════════════════════════
# B. 주문/포지션 체크
# ═══════════════════════════════════════════════════════════════

def check_rapid_exits(trades: list[dict]) -> list[dict]:
    """너무 빠른 청산."""
    issues = []
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        key = f"{t.get('symbol')}|{t.get('side')}|{t.get('entry_time')}"
        groups[key].append(t)

    for key, group_trades in groups.items():
        if not group_trades:
            continue
        total_holding = max((t.get("holding_minutes", 0) or 0) for t in group_trades)
        num_partials = len(group_trades)
        total_pnl = sum(t.get("realized_pnl_net_usd_estimate", 0) or 0 for t in group_trades)
        peak_roe = max((t.get("peak_roe_percent", 0) or 0) for t in group_trades)

        if total_holding <= 10 and num_partials >= 2:
            symbol = group_trades[0].get("symbol", "?")
            reasons = [t.get("exit_reason", "?") for t in group_trades]
            issues.append({
                "type": "rapid_exit",
                "severity": "WARNING",
                "symbol": symbol,
                "holding_minutes": total_holding,
                "partial_count": num_partials,
                "peak_roe_percent": round(peak_roe, 2),
                "total_pnl_usd": round(total_pnl, 4),
                "exit_reasons": reasons,
                "diagnosis": f"{symbol}: {total_holding:.0f}분 만에 {num_partials}회 부분청산 "
                             f"(peak ROE {peak_roe:.1f}%, 실현 ${total_pnl:.2f}). "
                             f"TP/protection 임계값이 레버리지 대비 너무 낮을 수 있음.",
                "fix_hint": "strategy_override.approved.json의 "
                            "proactive_take_profit_roe_thresholds, "
                            "profit_protection_arm/retrace 확인. "
                            "20x 레버리지에서 ROE 3%=가격 0.15% — 너무 낮음.",
            })

        for t in group_trades:
            pnl_gross = t.get("realized_pnl_usd_estimate", 0) or 0
            fee = t.get("estimated_round_trip_fee_usd", 0) or 0
            pnl_net = t.get("realized_pnl_net_usd_estimate", 0) or 0
            if pnl_gross > 0 and fee > 0 and fee / pnl_gross > 0.5:
                issues.append({
                    "type": "fee_eating_profit",
                    "severity": "WARNING",
                    "symbol": t.get("symbol", "?"),
                    "gross_pnl": round(pnl_gross, 4),
                    "fee": round(fee, 4),
                    "net_pnl": round(pnl_net, 4),
                    "fee_ratio": round(fee / pnl_gross, 2),
                    "diagnosis": f"수수료가 수익의 {fee/pnl_gross*100:.0f}% 차지 "
                                 f"(gross ${pnl_gross:.3f}, fee ${fee:.3f}, net ${pnl_net:.3f})",
                    "fix_hint": "TP 임계값 올려서 더 큰 수익에서 청산. "
                                "또는 min_expected_profit_usd_per_trade 상향.",
                })
    return issues


def check_exit_cascade(actions: list[dict]) -> list[dict]:
    """10분 내 exit 3회+ 연쇄 발동."""
    issues = []
    exits_by_symbol: dict[str, list[dict]] = defaultdict(list)

    for a in actions:
        reason = a.get("reason", "")
        if "TAKE_PROFIT" in reason or "PROTECTION" in reason or "PROFIT" in reason:
            symbol = a.get("symbol", "?")
            ts = a.get("timestamp", "")
            exits_by_symbol[symbol].append({"reason": reason, "timestamp": ts})

    for symbol, exits in exits_by_symbol.items():
        if len(exits) < 3:
            continue
        exits.sort(key=lambda x: x.get("timestamp", ""))
        for i in range(len(exits)):
            window = [exits[i]]
            for j in range(i + 1, len(exits)):
                try:
                    t1 = datetime.fromisoformat(exits[i]["timestamp"])
                    t2 = datetime.fromisoformat(exits[j]["timestamp"])
                    if (t2 - t1).total_seconds() <= 600:
                        window.append(exits[j])
                except (ValueError, TypeError):
                    pass
            if len(window) >= 3:
                reasons = list({e["reason"] for e in window})
                issues.append({
                    "type": "exit_cascade",
                    "severity": "WARNING",
                    "symbol": symbol,
                    "exit_count_in_10min": len(window),
                    "reasons": reasons,
                    "diagnosis": f"{symbol}: 10분 내 {len(window)}회 exit 연쇄 발동. "
                                 f"Exit 임계값 간 간격 부족.",
                    "fix_hint": "proactive_tp, profit_protection, unrealized_profit 임계값 간격 벌리기.",
                })
                break
    return issues


def check_order_rejected(lines: list[str]) -> list[dict]:
    """주문 거부 (잔고 부족, 최소금액 미달 등)."""
    issues = []
    reject_patterns = {
        "insufficient_balance": (r"insufficient|not enough|balance", "잔고 부족"),
        "min_amount": (r"less than.*minimum|below minimum|min.*amount", "최소금액 미달"),
        "max_position": (r"exceed.*max|position.*limit|over.*limit", "최대 포지션 초과"),
        "invalid_quantity": (r"invalid.*quantity|quantity.*invalid|lot.*size", "수량 오류"),
    }

    for rtype, (pattern, desc) in reject_patterns.items():
        matches = [l for l in lines if re.search(pattern, l, re.IGNORECASE)]
        if len(matches) >= 3:
            issues.append({
                "type": "order_rejected",
                "severity": "WARNING",
                "subtype": rtype,
                "count": len(matches),
                "sample": matches[-1][:200],
                "diagnosis": f"주문 거부({desc}) {len(matches)}회 반복",
                "fix_hint": f"{desc} 관련 코드 확인. "
                            f"risk.min_meaningful_futures_notional_usd, "
                            f"quantity_from_notional(), format_quantity() 확인.",
            })
    return issues


def check_coin_convert_loop(lines: list[str]) -> list[dict]:
    """코인 변환 무한 반복 (BTC 1e-06 같은 먼지)."""
    issues = []
    convert_lines = [l for l in lines if "COIN_CONVERT" in l and "selling" in l.lower()]
    if len(convert_lines) >= 10:
        # 같은 금액 반복인지 확인
        amounts = []
        for l in convert_lines:
            m = re.search(r"selling.*?(\S+)\s+(\w+USDT)", l)
            if m:
                amounts.append(f"{m.group(1)} {m.group(2)}")
        if amounts:
            most_common = Counter(amounts).most_common(1)[0]
            if most_common[1] >= 5:
                issues.append({
                    "type": "coin_convert_loop",
                    "severity": "WARNING",
                    "count": len(convert_lines),
                    "repeated_amount": most_common[0],
                    "repeat_count": most_common[1],
                    "diagnosis": f"코인 변환 반복: {most_common[0]} {most_common[1]}회 — "
                                 f"최소 거래금액 미달로 매도 실패 후 재시도 반복",
                    "fix_hint": "session.py _auto_convert_coin_futures_to_usdt()에서 "
                                "최소금액(1 USDT) 이하 먼지 무시 로직 추가. "
                                "_COIN_CONVERT_THRESHOLD_USD 확인.",
                })
    return issues


def check_position_mismatch(lines: list[str]) -> list[dict]:
    """paper vs exchange 포지션 불일치."""
    issues = []
    mismatch_lines = [l for l in lines
                      if "mismatch" in l.lower()
                      and "futures" in l.lower()
                      and "CONTAMINATION" not in l]
    if len(mismatch_lines) >= 5:
        issues.append({
            "type": "position_mismatch",
            "severity": "WARNING",
            "count": len(mismatch_lines),
            "diagnosis": f"paper↔exchange 포지션 불일치 {len(mismatch_lines)}회",
            "fix_hint": "self_healing이 처리하지만 반복되면: "
                        "1) 수동으로 열린 포지션이 있는지 확인 "
                        "2) disable_position_adoption=false 확인 "
                        "3) 데몬 재시작으로 sync 갱신",
        })
    return issues


def check_stale_position(lines: list[str]) -> list[dict]:
    """최대 보유시간 초과."""
    issues = []
    for line in lines:
        if "MAX_HOLDING" in line or "holding_exceeded" in line.lower():
            issues.append({
                "type": "stale_position",
                "severity": "WARNING",
                "diagnosis": "최대 보유 시간 초과 포지션 감지",
                "fix_hint": "exit_rules.futures_max_holding_minutes 확인",
                "raw": line[:200],
            })
    return issues


# ═══════════════════════════════════════════════════════════════
# C. 전략/의사결정 체크
# ═══════════════════════════════════════════════════════════════

def check_decision_rejection_rate(lines: list[str]) -> list[dict]:
    """진입 거부율."""
    issues = []
    decisions = [l for l in lines if "[DECISION]" in l]
    rejections = [l for l in lines if "[EXEC_PREFLIGHT]" in l and "allow=False" in l]

    if len(decisions) >= 20:
        total = len(decisions)
        rejected = len(rejections)
        rate = rejected / total * 100 if total > 0 else 0

        reason_counter: Counter = Counter()
        for line in rejections:
            m = re.search(r"reasons=(.+?)$", line)
            if m:
                for reason in m.group(1).split(","):
                    reason_counter[reason.strip()] += 1

        # MAX_CONCURRENT_FUTURES만 있으면 정상 (portfolio_focus)
        non_concurrent = {k: v for k, v in reason_counter.items()
                          if k != "MAX_CONCURRENT_FUTURES"}

        if rate >= 100 and non_concurrent:
            issues.append({
                "type": "high_rejection_rate",
                "severity": "CRITICAL",
                "total_decisions": total,
                "rejected": rejected,
                "rejection_rate_pct": round(rate, 1),
                "top_reasons": dict(reason_counter.most_common(5)),
                "diagnosis": f"진입 거부율 100% ({rejected}/{total}). "
                             f"봇이 아무 포지션도 못 잡음. "
                             f"주요 사유: {', '.join(f'{r}({c})' for r,c in Counter(non_concurrent).most_common(3))}",
                "fix_hint": "mode_thresholds의 futures_score_min, futures_liquidity_min 확인. "
                            "cost_gate.edge_to_cost_multiple_min이 너무 높지 않은지 확인. "
                            "symbol_eligibility.observe_only 설정 확인.",
            })
        elif rate >= 95 and non_concurrent:
            issues.append({
                "type": "high_rejection_rate",
                "severity": "WARNING",
                "total_decisions": total,
                "rejected": rejected,
                "rejection_rate_pct": round(rate, 1),
                "top_reasons": dict(reason_counter.most_common(5)),
                "diagnosis": f"진입 거부율 {rate:.0f}% ({rejected}/{total}). "
                             f"주요 사유: {', '.join(f'{r}({c})' for r,c in Counter(non_concurrent).most_common(3))}",
                "fix_hint": "거부 사유별 확인: SCORE_TOO_LOW → futures_score_min 낮추기, "
                            "LIQUIDITY_TOO_WEAK → futures_liquidity_min 낮추기, "
                            "VOL_TOO_HIGH → futures_volatility_penalty_max 올리기",
            })
    return issues


def check_zero_decisions(lines: list[str]) -> list[dict]:
    """의사결정 0건 — 데몬 stall."""
    issues = []
    heartbeats = [l for l in lines if "[HEARTBEAT]" in l]
    if len(heartbeats) >= 50:
        # 최근 50개 하트비트에서 decision 수 추출
        last_decisions = []
        for hb in heartbeats[-50:]:
            m = re.search(r"decisions=(\d+)", hb)
            if m:
                last_decisions.append(int(m.group(1)))

        # 100+ 하트비트 동안 0건이면 stall (50 하트비트 = ~25분, 100 = ~50분)
        if (last_decisions
                and max(last_decisions) == min(last_decisions)
                and len(last_decisions) >= 30
                and last_decisions[-1] == 0
                and len(heartbeats) >= 200):  # 최소 100분 이상 가동
            issues.append({
                "type": "zero_decisions",
                "severity": "CRITICAL",
                "heartbeat_count": len(last_decisions),
                "decision_count": last_decisions[-1],
                "diagnosis": f"최근 {len(last_decisions)}개 하트비트 동안 의사결정 증가 없음 "
                             f"(고정: {last_decisions[-1]}건) — 데몬 stall 또는 데이터 미수신",
                "fix_hint": "1) websocket 연결 상태 확인 (CONNECT 로그) "
                            "2) decision_interval 확인 (5분이면 50 하트비트 = ~25분은 정상 대기) "
                            "3) 데몬 재시작: kill PID && nohup bash scripts/quant_run_live_orders.sh",
            })
    return issues


def check_all_losses(trades: list[dict]) -> list[dict]:
    """최근 거래 전부 손실."""
    issues = []
    if len(trades) >= 5:
        recent = sorted(trades, key=lambda t: t.get("exit_time", ""), reverse=True)[:10]
        losses = [t for t in recent if (t.get("realized_pnl_net_usd_estimate", 0) or 0) < 0]
        if len(losses) == len(recent) and len(recent) >= 5:
            total_loss = sum(t.get("realized_pnl_net_usd_estimate", 0) or 0 for t in recent)
            issues.append({
                "type": "all_losses",
                "severity": "CRITICAL",
                "consecutive_losses": len(recent),
                "total_loss_usd": round(total_loss, 2),
                "diagnosis": f"최근 {len(recent)}건 연속 손실 (총 ${total_loss:.2f}). "
                             f"전략 고장 또는 시장 조건 극단적 변화.",
                "fix_hint": "1) loss_combo_downgrade가 작동하는지 확인 "
                            "2) 전략 파라미터 점검 (B3 MSB, coin_profiles) "
                            "3) 시장 방향과 진입 방향 일치 여부 "
                            "4) SL이 너무 타이트한지 확인 (stop_loss_roe_percent)",
            })
        elif len(losses) >= 7:
            total_loss = sum(t.get("realized_pnl_net_usd_estimate", 0) or 0 for t in losses)
            issues.append({
                "type": "all_losses",
                "severity": "WARNING",
                "loss_count": len(losses),
                "out_of": len(recent),
                "total_loss_usd": round(total_loss, 2),
                "diagnosis": f"최근 {len(recent)}건 중 {len(losses)}건 손실 (${total_loss:.2f})",
                "fix_hint": "loss_combo_downgrade 설정 확인. "
                            "cooldown_minutes, prune_loss_usd 값 점검.",
            })
    return issues


# ═══════════════════════════════════════════════════════════════
# D. 시스템 체크
# ═══════════════════════════════════════════════════════════════

def check_trailing_stop_health(lines: list[str]) -> list[dict]:
    """트레일링 스탑 성공/실패 비율."""
    issues = []
    successes = [l for l in lines if "TRAILING_STOP" in l and ("↑" in l or "↓" in l)]
    failures = [l for l in lines if "TRAILING_STOP" in l and "update failed" in l]

    total = len(successes) + len(failures)
    if total >= 5 and len(failures) / total > 0.5:
        # 에러 유형별 분류
        error_types: Counter = Counter()
        for f in failures:
            if "mark price" in f.lower():
                error_types["mark_price_violation"] += 1
            elif "40917" in f:
                error_types["stop_price_direction"] += 1
            else:
                error_types["other"] += 1

        issues.append({
            "type": "trailing_stop_failures",
            "severity": "CRITICAL" if len(failures) / total > 0.8 else "WARNING",
            "successes": len(successes),
            "failures": len(failures),
            "failure_rate_pct": round(len(failures) / total * 100, 1),
            "error_types": dict(error_types),
            "diagnosis": f"트레일링 스탑 실패율 {len(failures)/total*100:.0f}% "
                         f"({len(failures)}/{total}). 에러: {dict(error_types)}",
            "fix_hint": "session.py _update_trailing_stop() 확인: "
                        "1) format_trigger_price() 사용 여부 (소수점 정밀도) "
                        "2) mark price 버퍼 (new_sl >= mark_price * 0.997) "
                        "3) long은 SL < mark, short은 SL > mark "
                        "4) 활성화 임계값이 너무 낮지 않은지",
        })
    return issues


def check_equity_trend(lines: list[str]) -> list[dict]:
    """equity 지속 하락."""
    issues = []
    equities = []
    for line in lines:
        m = re.search(r"equity.*?\$(\d+\.\d+)\s*USDT", line, re.IGNORECASE)
        if m:
            equities.append(float(m.group(1)))

    if len(equities) >= 3:
        if all(equities[i] > equities[i + 1] for i in range(len(equities) - 1)):
            drop = (equities[0] - equities[-1]) / equities[0] * 100
            if drop > 5:
                issues.append({
                    "type": "equity_declining",
                    "severity": "WARNING" if drop < 15 else "CRITICAL",
                    "start_equity": equities[0],
                    "latest_equity": equities[-1],
                    "drop_pct": round(drop, 2),
                    "diagnosis": f"equity 지속 하락: ${equities[0]:.2f} → ${equities[-1]:.2f} "
                                 f"(-{drop:.1f}%)",
                    "fix_hint": "전략 수익성 점검. stop_loss_roe_percent, "
                                "진입 타이밍, 수수료 대비 수익률 확인. "
                                "15%+ 하락이면 data_collection_mode 전환 검토.",
                })
    return issues


def check_stall_recovery(lines: list[str]) -> list[dict]:
    """STALL_RECOVERY 발동."""
    issues = []
    stall_lines = [l for l in lines if "SELF_HEAL_STALL_RESTART" in l]
    if len(stall_lines) >= 3:
        issues.append({
            "type": "stall_recovery",
            "severity": "WARNING",
            "count": len(stall_lines),
            "diagnosis": f"self-healing stall recovery {len(stall_lines)}회 발동 — "
                         f"데몬이 반복적으로 멈추고 복구됨",
            "fix_hint": "1) 메모리 사용량 확인 (메모리 누수 가능) "
                        "2) CPU 과부하 확인 "
                        "3) live_supervisor.log에서 원인 확인 "
                        "4) 반복되면 데몬 완전 재시작",
        })
    return issues


def check_memory_usage() -> list[dict]:
    """메모리 사용량 점검."""
    issues = []
    try:
        import subprocess
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=10
        )
        total_kb = 0
        for line in result.stdout.splitlines():
            if "quant_binance" in line and "grep" not in line:
                parts = line.split()
                if len(parts) >= 6:
                    total_kb += int(parts[5])
        total_mb = total_kb / 1024
        if total_mb > 2000:
            issues.append({
                "type": "memory_leak",
                "severity": "CRITICAL",
                "memory_mb": round(total_mb),
                "diagnosis": f"quant_binance 메모리 {total_mb:.0f}MB (>2GB) — 메모리 누수 가능",
                "fix_hint": "데몬 재시작 필요. "
                            "paper_positions, live_trailing_stop_prices, "
                            "live_proactive_take_profit_keys 등 dict 증가 확인. "
                            "이전 세션 데이터 누적 여부.",
            })
        elif total_mb > 1000:
            issues.append({
                "type": "memory_leak",
                "severity": "WARNING",
                "memory_mb": round(total_mb),
                "diagnosis": f"quant_binance 메모리 {total_mb:.0f}MB (>1GB)",
                "fix_hint": "모니터링 지속. 2GB 넘으면 자동 재시작.",
            })
    except Exception:
        pass
    return issues


def check_config_sanity(override: dict) -> list[dict]:
    """override 설정값 이상 감지."""
    issues = []
    if not override:
        return issues

    risk = override.get("risk", {})
    exit_rules = override.get("exit_rules", {})
    live_risk = override.get("live_position_risk", {})
    exposure = override.get("futures_exposure", {})

    # 1. 레버리지 검증
    target_lev = risk.get("target_futures_leverage", 0)
    max_lev = risk.get("max_futures_leverage", 0)
    if target_lev > max_lev and max_lev > 0:
        issues.append({
            "type": "config_mismatch",
            "severity": "WARNING",
            "field": "leverage",
            "diagnosis": f"target_leverage({target_lev}) > max_leverage({max_lev})",
            "fix_hint": "target_futures_leverage <= max_futures_leverage 이어야 함",
        })

    # 2. SL > TP 검증
    sl = abs(live_risk.get("stop_loss_roe_percent", 0))
    tp = live_risk.get("take_profit_roe_percent", 0)
    if sl > 0 and tp > 0 and sl >= tp:
        issues.append({
            "type": "config_mismatch",
            "severity": "WARNING",
            "field": "sl_tp_ratio",
            "diagnosis": f"SL({sl}%) >= TP({tp}%) — 리스크/보상 비율 역전",
            "fix_hint": "take_profit_roe_percent > abs(stop_loss_roe_percent) 이어야 수익 가능",
        })

    # 3. Proactive TP 정렬 검증
    thresholds = exit_rules.get("futures_proactive_take_profit_roe_thresholds_percent", [])
    if thresholds and thresholds != sorted(thresholds):
        issues.append({
            "type": "config_mismatch",
            "severity": "CRITICAL",
            "field": "proactive_tp_order",
            "diagnosis": f"proactive TP 임계값 정렬 안됨: {thresholds}",
            "fix_hint": "오름차순 정렬 필요: [낮은값, 중간값, 높은값]",
        })

    # 4. Profit protection arm < retrace 검증
    arm = exit_rules.get("futures_profit_protection_arm_roe_percent", 0)
    retrace = exit_rules.get("futures_profit_protection_retrace_roe_percent", 0)
    if arm > 0 and retrace > 0 and retrace >= arm:
        issues.append({
            "type": "config_mismatch",
            "severity": "CRITICAL",
            "field": "profit_protection",
            "diagnosis": f"retrace({retrace}%) >= arm({arm}%) — profit protection 즉시 발동",
            "fix_hint": "retrace는 arm보다 작아야 함 (arm에서 retrace만큼 되돌릴 때 발동)",
        })

    # 5. 레버리지 대비 TP 임계값 검증
    if target_lev >= 10 and thresholds:
        min_tp = min(thresholds)
        price_move_pct = min_tp / target_lev
        if price_move_pct < 0.2:
            issues.append({
                "type": "config_mismatch",
                "severity": "WARNING",
                "field": "tp_vs_leverage",
                "diagnosis": f"첫 TP({min_tp}%) ÷ 레버리지({target_lev}x) = "
                             f"가격 {price_move_pct:.2f}% 움직임에 발동 — 너무 민감",
                "fix_hint": f"20x에서 최소 ROE 8%+ 권장 (가격 0.4%+ 움직임). "
                            f"현재 첫 TP는 가격 {price_move_pct:.2f}%에 발동.",
            })

    # 6. Universe 비어있는지
    universe = override.get("universe", [])
    if not universe:
        issues.append({
            "type": "config_mismatch",
            "severity": "CRITICAL",
            "field": "universe",
            "diagnosis": "universe가 비어있음 — 거래 가능 코인 없음",
            "fix_hint": "universe에 최소 1개 심볼 추가 (예: DOGEUSDT, XRPUSDT, SOLUSDT)",
        })

    # 7. data_collection_mode와 ensemble_signal_required 충돌
    dc_mode = override.get("data_collection_mode", False)
    ensemble_req = override.get("ensemble_signal_required", False)
    if dc_mode and ensemble_req:
        issues.append({
            "type": "config_mismatch",
            "severity": "WARNING",
            "field": "dc_ensemble_conflict",
            "diagnosis": "data_collection_mode=true인데 ensemble_signal_required=true — "
                         "데이터 수집 중 앙상블 게이트가 진입 차단",
            "fix_hint": "데이터 수집 모드에서는 ensemble_signal_required=false 권장",
        })

    # 8. portfolio_full_exit_only 확인
    if live_risk.get("portfolio_full_exit_only", False):
        issues.append({
            "type": "config_mismatch",
            "severity": "WARNING",
            "field": "portfolio_full_exit_only",
            "diagnosis": "portfolio_full_exit_only=true — 모든 개별 포지션 익절 비활성화됨",
            "fix_hint": "개별 TP가 필요하면 false로 변경",
        })

    # 9. pyramid 설정 검증
    pyramid = exposure.get("pyramid_enabled", False)
    max_adds = exposure.get("pyramid_max_adds_per_symbol", 0)
    if pyramid and max_adds <= 0:
        issues.append({
            "type": "config_mismatch",
            "severity": "WARNING",
            "field": "pyramid",
            "diagnosis": "pyramid_enabled=true인데 max_adds=0 — 피라미딩 비활성화 상태",
            "fix_hint": "pyramid_max_adds_per_symbol > 0 설정 또는 pyramid_enabled=false",
        })

    return issues


def check_log_file_health() -> list[dict]:
    """로그 파일 건전성."""
    issues = []
    daemon_log = RUNTIME / "daemon_restart.log"
    supervisor_log = RUNTIME / "live_supervisor.log"

    for log_path, name, warn_mb, crit_mb in [
        (daemon_log, "daemon_restart.log", 100, 500),
        (supervisor_log, "live_supervisor.log", 200, 1000),
    ]:
        if log_path.exists():
            size_mb = log_path.stat().st_size / (1024 * 1024)
            if size_mb > crit_mb:
                issues.append({
                    "type": "log_bloat",
                    "severity": "CRITICAL",
                    "file": name,
                    "size_mb": round(size_mb),
                    "diagnosis": f"{name} {size_mb:.0f}MB (>{crit_mb}MB) — 디스크 압박",
                    "fix_hint": f"로그 로테이션: mv {log_path} {log_path}.old "
                                f"또는 tail -10000 {log_path} > {log_path}.tmp && "
                                f"mv {log_path}.tmp {log_path}",
                })
            elif size_mb > warn_mb:
                issues.append({
                    "type": "log_bloat",
                    "severity": "WARNING",
                    "file": name,
                    "size_mb": round(size_mb),
                    "diagnosis": f"{name} {size_mb:.0f}MB (>{warn_mb}MB)",
                    "fix_hint": "health audit의 자동 로테이션이 처리할 예정",
                })
    return issues


def check_orphan_positions(syncs: list[dict]) -> list[dict]:
    """거래소에 포지션 있는데 봇이 모르는 경우 (고아 포지션)."""
    issues = []
    if not syncs:
        return issues

    latest = syncs[-1]
    snap = latest.get("account_snapshot", {})
    accounts = snap.get("accounts", [])

    for acc in accounts:
        upl = float(acc.get("unrealizedPL", 0) or 0)
        crossed_margin = float(acc.get("crossedMargin", 0) or 0)

        # 마진이 있는데 UPL이 크게 마이너스면 문제
        if crossed_margin > 0 and upl < -5.0:
            issues.append({
                "type": "large_unrealized_loss",
                "severity": "CRITICAL",
                "unrealized_pnl": round(upl, 2),
                "margin_used": round(crossed_margin, 2),
                "diagnosis": f"미실현 손실 ${upl:.2f} (마진 ${crossed_margin:.2f} 사용 중)",
                "fix_hint": "포지션 확인: Bitget 앱에서 열린 포지션 확인. "
                            "stop_loss_roe_percent에 의해 자동 청산될 예정. "
                            "즉시 청산 필요하면 수동 청산.",
            })
    return issues


def check_sync_freshness(lines: list[str]) -> list[dict]:
    """REST sync 최신성 확인 — account_sync.jsonl 파일 mtime 기반."""
    issues = []
    # 최신 세션의 account_sync.jsonl 파일 수정 시간으로 판단
    base = RUNTIME / "output" / "paper-live-shell"
    if not base.exists():
        return issues
    sessions = sorted(
        [d for d in base.iterdir() if d.is_dir() and d.name != "latest"],
        reverse=True,
    )
    sync_file = None
    for sd in sessions[:2]:
        sf = sd / "logs" / "account_sync.jsonl"
        if sf.exists() and sf.stat().st_size > 0:
            sync_file = sf
            break

    if sync_file:
        age_min = (datetime.now(tz=timezone.utc)
                   - datetime.fromtimestamp(sync_file.stat().st_mtime, tz=timezone.utc)
                   ).total_seconds() / 60
        if age_min > 30:
            issues.append({
                "type": "sync_stale",
                "severity": "CRITICAL",
                "last_sync_minutes_ago": round(age_min),
                "diagnosis": f"마지막 account sync {age_min:.0f}분 전 — 데이터 갱신 지연",
                "fix_hint": "데몬 프로세스 확인. 멈췄으면 재시작.",
            })
        elif age_min > 10:
            issues.append({
                "type": "sync_stale",
                "severity": "WARNING",
                "last_sync_minutes_ago": round(age_min),
                "diagnosis": f"마지막 account sync {age_min:.0f}분 전",
                "fix_hint": "모니터링. 30분 넘으면 재시작 필요.",
            })
    else:
        # sync 파일 자체가 없고 하트비트가 충분하면
        heartbeats = [l for l in lines if "[HEARTBEAT]" in l]
        if len(heartbeats) >= 200:
            issues.append({
                "type": "sync_stale",
                "severity": "CRITICAL",
                "diagnosis": "account_sync 파일 없음 — REST 데이터 갱신 중단",
                "fix_hint": "데몬 재시작 필요.",
            })
    return issues


# ═══════════════════════════════════════════════════════════════
# 메인
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    print("[BUG_DETECTOR] 런타임 버그/에러 패턴 스캔 시작...", flush=True)

    daemon_lines = _read_recent_daemon_log()
    supervisor_lines = _read_supervisor_log()
    # API/네트워크 에러는 현재 세션(daemon) + supervisor 최근 500줄만
    all_lines = daemon_lines + supervisor_lines[-500:]
    trades = _read_closed_trades()
    actions = _read_position_actions()
    syncs = _read_account_sync()
    override = _read_override()

    all_issues: list[dict] = []

    checks = [
        # A. API/네트워크
        ("API 에러 반복", check_repeated_api_errors(all_lines)),
        ("DNS 실패", check_dns_failure(all_lines)),
        ("REST 재시도 한계", check_transport_exhausted(all_lines)),
        ("Rate Limit", check_rate_limited(all_lines)),
        ("웹소켓 안정성", check_websocket_stability(daemon_lines)),
        # B. 주문/포지션
        ("급속 청산", check_rapid_exits(trades)),
        ("Exit 연쇄", check_exit_cascade(actions)),
        ("주문 거부", check_order_rejected(all_lines)),
        ("코인변환 루프", check_coin_convert_loop(all_lines)),
        ("포지션 불일치", check_position_mismatch(all_lines)),
        ("장기 보유", check_stale_position(daemon_lines)),
        # C. 전략/의사결정
        ("진입 거부율", check_decision_rejection_rate(daemon_lines)),
        ("의사결정 stall", check_zero_decisions(daemon_lines)),
        ("연속 손실", check_all_losses(trades)),
        # D. 시스템
        ("트레일링 스탑", check_trailing_stop_health(daemon_lines)),
        ("Equity 추이", check_equity_trend(daemon_lines)),
        ("Stall Recovery", check_stall_recovery(all_lines)),
        ("메모리 사용량", check_memory_usage()),
        ("설정값 검증", check_config_sanity(override)),
        ("로그 파일", check_log_file_health()),
        ("고아 포지션", check_orphan_positions(syncs)),
        ("Sync 최신성", check_sync_freshness(daemon_lines)),
    ]

    for name, issues in checks:
        if issues:
            print(f"  [{name}] {len(issues)}건 감지", flush=True)
            all_issues.extend(issues)
        else:
            print(f"  [{name}] OK", flush=True)

    # 결과 저장
    result = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "total_issues": len(all_issues),
        "critical_count": sum(1 for i in all_issues if i.get("severity") == "CRITICAL"),
        "warning_count": sum(1 for i in all_issues if i.get("severity") == "WARNING"),
        "issues": all_issues,
    }

    result_path = RUNTIME / "artifacts" / "bug_detector_result.json"
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    print(f"\n[BUG_DETECTOR] 결과: CRITICAL={result['critical_count']} WARNING={result['warning_count']}", flush=True)
    for issue in all_issues:
        severity = issue.get("severity", "?")
        itype = issue.get("type", "?")
        diag = issue.get("diagnosis", "")
        print(f"  [{severity}] {itype}: {diag}", flush=True)

    if result["critical_count"] > 0:
        sys.exit(2)
    elif result["warning_count"] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
