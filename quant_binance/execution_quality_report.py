from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExecutionQualityReport:
    base_dir: str
    generated_at: str
    lookback_days: int
    run_count: int
    live_order_count: int
    tested_order_count: int
    order_error_count: int
    accepted_live_order_count: int
    estimated_live_acceptance_rate: float
    top_error_codes: tuple[dict[str, object], ...]
    symbol_order_summary: tuple[dict[str, object], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "base_dir": self.base_dir,
            "generated_at": self.generated_at,
            "lookback_days": self.lookback_days,
            "run_count": self.run_count,
            "live_order_count": self.live_order_count,
            "tested_order_count": self.tested_order_count,
            "order_error_count": self.order_error_count,
            "accepted_live_order_count": self.accepted_live_order_count,
            "estimated_live_acceptance_rate": self.estimated_live_acceptance_rate,
            "top_error_codes": list(self.top_error_codes),
            "symbol_order_summary": list(self.symbol_order_summary),
        }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _resolve_recent_runs(*, base_dir: Path, lookback_days: int) -> list[Path]:
    mode_root = base_dir / "output" / "paper-live-shell"
    if not mode_root.exists():
        return []
    threshold = datetime.now(UTC) - timedelta(days=lookback_days)
    runs: list[Path] = []
    for candidate in mode_root.iterdir():
        if not candidate.is_dir() or candidate.name == "latest":
            continue
        modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
        if modified >= threshold:
            runs.append(candidate)
    runs.sort(key=lambda p: p.stat().st_mtime)
    return runs


def _extract_error_code(message: str) -> str:
    if '"code":"' in message:
        try:
            return message.split('"code":"', 1)[1].split('"', 1)[0]
        except Exception:
            pass
    if '"code":' in message:
        try:
            tail = message.split('"code":', 1)[1].lstrip()
            digits = []
            for char in tail:
                if char.isdigit():
                    digits.append(char)
                    continue
                if digits:
                    break
            if digits:
                return "".join(digits)
        except Exception:
            pass
    for token in message.replace('"', " ").replace(":", " ").split():
        if token.isdigit():
            return token
    return "unknown"


def build_execution_quality_report(*, base_dir: str | Path = "quant_runtime", lookback_days: int = 7) -> ExecutionQualityReport:
    root = Path(base_dir)
    runs = _resolve_recent_runs(base_dir=root, lookback_days=lookback_days)
    generated_at = datetime.now(UTC).isoformat()

    live_order_count = 0
    tested_order_count = 0
    order_error_count = 0
    accepted_live_order_count = 0
    error_codes: Counter[str] = Counter()
    by_symbol: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {
            "live_order_count": 0,
            "accepted_live_order_count": 0,
            "tested_order_count": 0,
            "order_error_count": 0,
        }
    )

    for run_dir in runs:
        logs_dir = run_dir / "logs"
        live_orders = _load_jsonl(logs_dir / "live_orders.jsonl")
        tested_orders = _load_jsonl(logs_dir / "tested_orders.jsonl")
        order_errors = _load_jsonl(logs_dir / "order_errors.jsonl")

        live_order_count += len(live_orders)
        tested_order_count += len(tested_orders)
        order_error_count += len(order_errors)

        for row in live_orders:
            symbol = str(row.get("symbol", ""))
            accepted = bool(row.get("accepted", False))
            if accepted:
                accepted_live_order_count += 1
            bucket = by_symbol[symbol]
            bucket["live_order_count"] = int(bucket["live_order_count"]) + 1
            if accepted:
                bucket["accepted_live_order_count"] = int(bucket["accepted_live_order_count"]) + 1

        for row in tested_orders:
            symbol = str(row.get("symbol", ""))
            bucket = by_symbol[symbol]
            bucket["tested_order_count"] = int(bucket["tested_order_count"]) + 1

        for row in order_errors:
            symbol = str(row.get("symbol", ""))
            message = str(row.get("error_message") or row.get("response") or "")
            code = _extract_error_code(message)
            error_codes[code] += 1
            bucket = by_symbol[symbol]
            bucket["order_error_count"] = int(bucket["order_error_count"]) + 1

    symbol_rows: list[dict[str, object]] = []
    for symbol, bucket in by_symbol.items():
        live_count = int(bucket["live_order_count"])
        accepted_count = int(bucket["accepted_live_order_count"])
        symbol_rows.append(
            {
                "symbol": symbol,
                "live_order_count": live_count,
                "accepted_live_order_count": accepted_count,
                "tested_order_count": int(bucket["tested_order_count"]),
                "order_error_count": int(bucket["order_error_count"]),
                "estimated_live_acceptance_rate": round(accepted_count / live_count, 6) if live_count else 0.0,
            }
        )
    symbol_rows.sort(
        key=lambda item: (
            -int(item["order_error_count"]),
            float(item["estimated_live_acceptance_rate"]),
            str(item["symbol"]),
        )
    )

    top_error_codes = tuple(
        {"code": code, "count": count}
        for code, count in error_codes.most_common(10)
    )

    acceptance_rate = round(accepted_live_order_count / live_order_count, 6) if live_order_count else 0.0
    return ExecutionQualityReport(
        base_dir=str(root),
        generated_at=generated_at,
        lookback_days=lookback_days,
        run_count=len(runs),
        live_order_count=live_order_count,
        tested_order_count=tested_order_count,
        order_error_count=order_error_count,
        accepted_live_order_count=accepted_live_order_count,
        estimated_live_acceptance_rate=acceptance_rate,
        top_error_codes=top_error_codes,
        symbol_order_summary=tuple(symbol_rows),
    )


def write_execution_quality_report(*, report: ExecutionQualityReport, output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return target
