"""
B3 MSB OOS 검증 + strategy_override 자동 업데이트
==================================================
freqtrade hyperopt 결과에서 best params를 추출하고,
OOS 기간 백테스트를 돌려 안전성 게이트를 통과하면
strategy_override.approved.json을 업데이트한다.

Exit codes:
  0 = OOS PASS, params updated
  1 = OOS FAIL or error, params unchanged
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Safety gates ──
MIN_OOS_TRADES = 5
MIN_OOS_WIN_RATE = 0.45  # 45%
MAX_OOS_MAX_DD_PCT = 15.0  # 15%
MIN_OOS_PNL_PCT = 0.0  # positive

# Fields to extract from hyperopt best result
PARAM_MAP = {
    "swing_window": ("swing_window", int),
    "atr_tp_mult": ("atr_tp_multiple", float),
    "atr_sl_mult": ("atr_sl_multiple", float),
    "breakout_buffer": ("breakout_buffer_pct", lambda v: round(float(v) / 100.0, 6)),
    "adx_min": ("adx_min", int),
    "use_ema_filter": ("use_ema_filter", bool),
    "min_swing_atr": ("min_swing_size_atr", float),
    "rsi_upper": ("rsi_upper", int),
    "rsi_lower": ("rsi_lower", int),
    "vol_z_min": ("vol_z_min", float),
}


def _send_telegram(repo: Path, status: str, reason: str, details: str = "") -> None:
    """Send telegram notification via the helper script."""
    script = repo / "scripts" / "b3_msb_notify.py"
    if script.exists():
        cmd = [
            sys.executable, str(script),
            "--status", status,
            "--reason", reason,
        ]
        if details:
            cmd.extend(["--details", details])
        subprocess.run(cmd, timeout=30, capture_output=True)


def _extract_best_params(ft_dir: Path) -> dict | None:
    """Extract best hyperopt params from freqtrade."""
    result = subprocess.run(
        [
            "freqtrade", "hyperopt-show", "--best",
            "--config", str(ft_dir / "config.json"),
            "--no-color", "--print-json",
        ],
        capture_output=True, text=True, cwd=str(ft_dir), timeout=60,
    )
    if result.returncode != 0:
        print(f"[OOS] hyperopt-show failed: {result.stderr[:500]}")
        return None

    # Find JSON in output (freqtrade prints mixed text + JSON)
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    # Try to find JSON block in full output
    match = re.search(r'\{[^{}]*"swing_window"[^{}]*\}', result.stdout)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Fallback: parse "Buy hyperopt params" section
    params = {}
    in_buy = False
    for line in result.stdout.split("\n"):
        if "buy hyperopt params" in line.lower() or "buy params" in line.lower():
            in_buy = True
            continue
        if in_buy and ":" in line:
            key, _, val = line.partition(":")
            key = key.strip().strip('"').strip("'")
            val = val.strip().rstrip(",").strip('"').strip("'")
            if key in PARAM_MAP:
                params[key] = val
        if in_buy and (line.strip() == "" or line.strip().startswith("}")):
            if params:
                break

    if params:
        return params

    print(f"[OOS] Could not parse best params from hyperopt output")
    print(f"[OOS] stdout (last 500 chars): {result.stdout[-500:]}")
    return None


def _run_oos_backtest(ft_dir: Path, oos_start: str, today: str) -> dict | None:
    """Run backtest on OOS period and return parsed results."""
    result = subprocess.run(
        [
            "freqtrade", "backtesting",
            "--config", str(ft_dir / "config.json"),
            "--strategy", "B3_MSB_Strategy",
            "--timerange", f"{oos_start}-{today}",
            "--no-color",
        ],
        capture_output=True, text=True, cwd=str(ft_dir), timeout=300,
    )
    if result.returncode != 0:
        print(f"[OOS] Backtest failed: {result.stderr[:500]}")
        return None

    stdout = result.stdout

    # Parse key metrics from backtest output
    metrics = {}

    # Total trades
    m = re.search(r'(\d+)\s+trades', stdout, re.IGNORECASE)
    if m:
        metrics["trades"] = int(m.group(1))

    # Win rate - look for "Wins" or "W/D/L"
    m = re.search(r'(\d+)\s*/\s*(\d+)\s*/\s*(\d+)', stdout)
    if m:
        wins, draws, losses = int(m.group(1)), int(m.group(2)), int(m.group(3))
        total = wins + draws + losses
        metrics["trades"] = total
        metrics["wins"] = wins
        metrics["win_rate"] = wins / max(total, 1)

    # Look for "Win%" or "Winrate"
    m = re.search(r'(?:win\s*%?|winrate)[:\s]+(\d+\.?\d*)\s*%?', stdout, re.IGNORECASE)
    if m:
        metrics["win_rate"] = float(m.group(1)) / 100.0

    # Total profit %
    m = re.search(r'(?:total\s+)?profit[:\s]+(-?\d+\.?\d*)\s*%', stdout, re.IGNORECASE)
    if m:
        metrics["total_pnl_pct"] = float(m.group(1))

    # Max drawdown
    m = re.search(r'(?:max\s+)?drawdown[:\s]+(-?\d+\.?\d*)\s*%', stdout, re.IGNORECASE)
    if m:
        metrics["max_dd_pct"] = abs(float(m.group(1)))

    # Profit factor
    m = re.search(r'profit\s*factor[:\s]+(\d+\.?\d*)', stdout, re.IGNORECASE)
    if m:
        metrics["profit_factor"] = float(m.group(1))

    # Also try to get from backtest results JSON
    results_dir = ft_dir / "user_data" / "backtest_results"
    if results_dir.exists():
        for f in sorted(results_dir.glob("backtest-result-*.json"), reverse=True):
            try:
                bt_data = json.loads(f.read_text())
                if "strategy" in bt_data:
                    for strat_name, strat_data in bt_data["strategy"].items():
                        metrics["trades"] = strat_data.get("total_trades", metrics.get("trades", 0))
                        metrics["win_rate"] = strat_data.get("wins", 0) / max(strat_data.get("total_trades", 1), 1)
                        metrics["total_pnl_pct"] = strat_data.get("profit_total", 0) * 100
                        metrics["max_dd_pct"] = abs(strat_data.get("max_drawdown_abs", 0) / max(strat_data.get("starting_balance", 200), 1)) * 100
                        break
                break
            except (json.JSONDecodeError, OSError, KeyError):
                continue

    if not metrics.get("trades"):
        print(f"[OOS] Could not parse backtest results")
        print(f"[OOS] stdout (last 1000 chars): {stdout[-1000:]}")
        return None

    return metrics


def _validate_oos(metrics: dict) -> tuple[bool, list[str]]:
    """Check OOS results against safety gates. Returns (passed, reasons)."""
    reasons = []

    trades = metrics.get("trades", 0)
    if trades < MIN_OOS_TRADES:
        reasons.append(f"trades={trades} < {MIN_OOS_TRADES}")

    wr = metrics.get("win_rate", 0)
    if wr < MIN_OOS_WIN_RATE:
        reasons.append(f"win_rate={wr:.1%} < {MIN_OOS_WIN_RATE:.0%}")

    dd = metrics.get("max_dd_pct", 999)
    if dd > MAX_OOS_MAX_DD_PCT:
        reasons.append(f"max_dd={dd:.1f}% > {MAX_OOS_MAX_DD_PCT}%")

    pnl = metrics.get("total_pnl_pct", -999)
    if pnl <= MIN_OOS_PNL_PCT:
        reasons.append(f"pnl={pnl:.2f}% <= {MIN_OOS_PNL_PCT}%")

    return len(reasons) == 0, reasons


def _convert_params(raw: dict) -> dict:
    """Convert hyperopt param names to strategy_override field names."""
    converted = {}
    for ht_key, (override_key, cast_fn) in PARAM_MAP.items():
        if ht_key in raw:
            val = raw[ht_key]
            try:
                converted[override_key] = cast_fn(val)
            except (ValueError, TypeError):
                converted[override_key] = val
    return converted


def _update_override(
    override_path: Path,
    new_params: dict,
    oos_metrics: dict,
    train_start: str,
    oos_start: str,
    today: str,
) -> None:
    """Update strategy_override.approved.json with new B3 MSB params."""
    current = json.loads(override_path.read_text(encoding="utf-8"))

    b3 = current.get("b3_msb_strategy", {})
    b3.update(new_params)
    b3["optimized_at"] = datetime.now(tz=timezone.utc).isoformat()
    b3["optimizer"] = "freqtrade_hyperopt_auto"
    b3["train_period"] = f"{train_start[:4]}-{train_start[4:6]}-{train_start[6:]} ~ {oos_start[:4]}-{oos_start[4:6]}-{oos_start[6:]}"
    b3["oos_period"] = f"{oos_start[:4]}-{oos_start[4:6]}-{oos_start[6:]} ~ {today[:4]}-{today[4:6]}-{today[6:]}"
    b3["oos_trades"] = oos_metrics.get("trades", 0)
    b3["oos_win_rate_pct"] = round(oos_metrics.get("win_rate", 0) * 100, 1)
    b3["oos_pnl_pct"] = round(oos_metrics.get("total_pnl_pct", 0), 2)
    b3["oos_max_dd_pct"] = round(oos_metrics.get("max_dd_pct", 0), 2)
    b3["note"] = "Auto-reoptimized by b3_msb_auto_reoptimize pipeline. OOS PASS."

    current["b3_msb_strategy"] = b3

    # Atomic write
    tmp_path = override_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp_path), str(override_path))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ft-dir", required=True)
    parser.add_argument("--override-path", required=True)
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--train-start", required=True)
    parser.add_argument("--oos-start", required=True)
    parser.add_argument("--today", required=True)
    args = parser.parse_args()

    ft_dir = Path(args.ft_dir)
    override_path = Path(args.override_path)
    log_dir = Path(args.log_dir)
    repo = Path(args.ft_dir).parent

    # Step 1: Extract best params
    print("[OOS] Extracting best hyperopt params...")
    raw_params = _extract_best_params(ft_dir)
    if not raw_params:
        _send_telegram(repo, "FAIL", "Cannot extract hyperopt best params")
        sys.exit(1)

    print(f"[OOS] Raw params: {json.dumps(raw_params, default=str)}")
    converted = _convert_params(raw_params)
    print(f"[OOS] Converted: {json.dumps(converted, default=str)}")

    # Save params for audit
    (log_dir / f"best_params_{args.today}.json").write_text(
        json.dumps({"raw": raw_params, "converted": converted}, indent=2, default=str),
        encoding="utf-8",
    )

    # Step 2: Write best params to strategy for OOS backtest
    # (freqtrade uses the last hyperopt result automatically)

    # Step 3: Run OOS backtest
    print(f"[OOS] Running OOS backtest: {args.oos_start} ~ {args.today}")
    oos_metrics = _run_oos_backtest(ft_dir, args.oos_start, args.today)
    if not oos_metrics:
        _send_telegram(repo, "FAIL", "OOS backtest failed or no results")
        sys.exit(1)

    print(f"[OOS] Metrics: {json.dumps(oos_metrics, default=str)}")

    # Save metrics for audit
    (log_dir / f"oos_metrics_{args.today}.json").write_text(
        json.dumps(oos_metrics, indent=2, default=str),
        encoding="utf-8",
    )

    # Step 4: Validate
    passed, fail_reasons = _validate_oos(oos_metrics)

    if not passed:
        reason_str = "; ".join(fail_reasons)
        print(f"[OOS] FAIL: {reason_str}")
        details = (
            f"Trades: {oos_metrics.get('trades', '?')}\n"
            f"WR: {oos_metrics.get('win_rate', 0):.1%}\n"
            f"PnL: {oos_metrics.get('total_pnl_pct', 0):.2f}%\n"
            f"DD: {oos_metrics.get('max_dd_pct', 0):.1f}%\n"
            f"Fail: {reason_str}"
        )
        _send_telegram(repo, "FAIL", f"OOS validation failed: {reason_str}", details)
        sys.exit(1)

    # Step 5: Compare with current params (don't downgrade)
    current_override = json.loads(override_path.read_text(encoding="utf-8"))
    current_b3 = current_override.get("b3_msb_strategy", {})
    current_oos_pnl = current_b3.get("oos_pnl_pct", 0)

    new_oos_pnl = oos_metrics.get("total_pnl_pct", 0)
    if new_oos_pnl < current_oos_pnl * 0.5 and current_oos_pnl > 0:
        reason = f"New OOS ({new_oos_pnl:.2f}%) significantly worse than current ({current_oos_pnl:.2f}%)"
        print(f"[OOS] SKIP: {reason}")
        _send_telegram(repo, "SKIP", reason)
        sys.exit(1)

    # Step 6: Update override
    print("[OOS] PASS — updating strategy_override.approved.json")
    _update_override(
        override_path=override_path,
        new_params=converted,
        oos_metrics=oos_metrics,
        train_start=args.train_start,
        oos_start=args.oos_start,
        today=args.today,
    )

    details = (
        f"B3 MSB Auto-Reoptimized\n"
        f"Train: {args.train_start} ~ {args.oos_start}\n"
        f"OOS: {args.oos_start} ~ {args.today}\n"
        f"Trades: {oos_metrics.get('trades', '?')}\n"
        f"WR: {oos_metrics.get('win_rate', 0):.1%}\n"
        f"PnL: {oos_metrics.get('total_pnl_pct', 0):.2f}%\n"
        f"DD: {oos_metrics.get('max_dd_pct', 0):.1f}%\n"
        f"Params: {json.dumps(converted, default=str)}"
    )
    _send_telegram(repo, "PASS", "OOS passed, params updated", details)
    print("[OOS] Done")


if __name__ == "__main__":
    main()
