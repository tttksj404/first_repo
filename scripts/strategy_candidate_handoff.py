#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ARTIFACTS = Path(__file__).resolve().parent.parent / "quant_runtime" / "artifacts"
ROTATION_SHORTLIST = ARTIFACTS / "rotation_strategy_shortlist.json"
CARRY_SCAN = ARTIFACTS / "carry_basis_strategy_scan.json"
OUTPUT_JSON = ARTIFACTS / "strategy_candidate_handoff.json"
OUTPUT_MD = ARTIFACTS / "strategy_candidate_handoff.md"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _rotation_candidates(payload: dict) -> list[dict]:
    return list(payload.get("candidates") or [])


def _carry_candidates(payload: dict) -> list[dict]:
    candidates = list(payload.get("validated_top_results") or payload.get("top_results") or [])
    selected: list[dict] = []
    seen: set[tuple[object, ...]] = set()
    for row in candidates:
        if int(row.get("trades", 0)) < 7:
            continue
        if float(row.get("profit_factor", 0.0)) < 1.5:
            continue
        if int(row.get("positive_folds", 0)) < 3:
            continue
        if float(row.get("stressed_total_return_bps", 0.0)) <= 0.0:
            continue
        key = (
            row.get("symbol"),
            row.get("funding_threshold"),
            row.get("basis_threshold_bps"),
            row.get("hold_hours"),
            row.get("stop_bps"),
            row.get("tp_bps"),
        )
        if key in seen:
            continue
        seen.add(key)
        selected.append(row)
    return selected[:10]


def main() -> int:
    rotation = _load_json(ROTATION_SHORTLIST)
    carry = _load_json(CARRY_SCAN)
    rotation_candidates = _rotation_candidates(rotation)
    carry_candidates = _carry_candidates(carry)

    payload = {
        "generated_by": "strategy_candidate_handoff",
        "rotation_source": str(ROTATION_SHORTLIST),
        "carry_source": str(CARRY_SCAN),
        "rotation_candidates": rotation_candidates,
        "carry_candidates": carry_candidates,
        "next_actions": [
            "rotation 후보는 majors-only 우선으로 recent comparison 또는 별도 walk-forward 재검증",
            "carry 후보는 SOLUSDT 우선으로 최근 30일/60일 구간 재검증과 paper 모니터링",
            "rotation과 carry를 동일 승격 게이트(PF/MDD/WF/cost stress)로 비교",
        ],
    }
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# Strategy Candidate Handoff",
        "",
        "## Rotation Candidates",
    ]
    if rotation_candidates:
        for row in rotation_candidates[:5]:
            lines.append(
                f"- `{row['universe']}` lookback={row['lookback_hours']}h rebalance={row['rebalance_hours']}h "
                f"top_k={row['top_k']} score={row['score_mode']} positive={row['require_positive']} ema={row['ema_filter']} "
                f"return={float(row['total_return_pct']):+.2f}% PF={float(row['profit_factor']):.2f} "
                f"MDD={float(row['max_drawdown_pct']):.2f}% Sharpe={float(row['sharpe_like']):.2f}"
            )
    else:
        lines.append("- no candidates passed the shortlist filter")
    lines.extend(["", "## Carry / Basis Candidates"])
    if carry_candidates:
        for row in carry_candidates[:5]:
            lines.append(
                f"- `{row['symbol']}` funding>={row['funding_threshold']:.5f} basis>={row['basis_threshold_bps']:.1f}bps "
                f"hold={row['hold_hours']}h stop={row['stop_bps']:.0f} tp={row['tp_bps']:.0f} "
                f"n={row['trades']} PF={float(row['profit_factor']):.2f} WF={row.get('positive_folds', 0)}/4 "
                f"stress24={float(row.get('stressed_total_return_bps', 0.0)):+.1f}bps"
            )
    else:
        lines.append("- no carry/basis candidates passed the handoff filter")
    lines.extend(
        [
            "",
            "## Suggested Next Commands",
            f"- `python3 {Path('scripts/rotation_strategy_scan.py')} --workers 4`",
            f"- `python3 {Path('scripts/rotation_strategy_shortlist.py')}`",
            f"- `python3 {Path('scripts/carry_basis_strategy_scan.py')}`",
            f"- `python3 {Path('scripts/strategy_candidate_handoff.py')}`",
        ]
    )
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 100)
    print("STRATEGY CANDIDATE HANDOFF")
    print("=" * 100)
    print(f"saved_json={OUTPUT_JSON}")
    print(f"saved_md={OUTPUT_MD}")
    print(f"rotation_candidates={len(rotation_candidates)} carry_candidates={len(carry_candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
