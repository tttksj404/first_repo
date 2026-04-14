#!/usr/bin/env python3
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "quant_runtime" / "artifacts"
RANKED_PATH = ARTIFACTS / "strategy_candidate_ranked.json"
APPROVED_OVERRIDE = ARTIFACTS / "strategy_override.approved.json"
OUTPUT_JSON = ARTIFACTS / "strategy_execution_bundle.json"
OUTPUT_MD = ARTIFACTS / "strategy_execution_bundle.md"
OVERRIDE_DIR = ARTIFACTS / "candidate_overrides"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _carry_override(base: dict, metrics: dict, *, rank: int) -> dict:
    override = deepcopy(base)
    symbol = str(metrics["symbol"])
    funding_cfg = dict(override.get("funding_rate_strategy") or {})
    funding_cfg.update(
        {
            "enabled": True,
            "threshold": float(metrics["funding_threshold"]),
            "max_hold_hours": int(metrics["hold_hours"]),
            "symbols": [symbol],
        }
    )
    override["funding_rate_strategy"] = funding_cfg
    override["universe"] = [symbol]
    override.setdefault("futures_exposure", {})
    override["futures_exposure"]["priority_symbols"] = [symbol]
    override["futures_exposure"]["major_symbols"] = [symbol]
    override.setdefault("spot_support", {})
    override["spot_support"]["priority_symbols"] = [symbol]
    override["_candidate_meta"] = {
        "family": "carry",
        "rank": rank,
        "source": str(RANKED_PATH),
        "candidate_summary": metrics,
        "approximation_note": "runtime funding_rate_strategy uses ATR-based exits; threshold/hold/symbol mapping is exact but stop/tp semantics are approximate",
    }
    return override


def _rotation_review_bundle(metrics: dict, *, rank: int) -> dict:
    symbols = list(metrics.get("symbols") or [])
    return {
        "family": "rotation",
        "rank": rank,
        "source": str(RANKED_PATH),
        "candidate_summary": metrics,
        "env": {
            "UNIVERSE_SYMBOLS": ",".join(symbols),
        },
        "commands": [
            "python3 scripts/rotation_strategy_scan.py --workers 4",
            "python3 scripts/rotation_strategy_shortlist.py",
            "python3 scripts/strategy_candidate_ranker.py",
            "sh scripts/quant_report.sh quant_runtime",
        ],
        "notes": [
            "rotation logic is not natively implemented inside quant_binance runtime yet",
            "this bundle constrains the universe and preserves the candidate config for manual/review-driven paper monitoring",
        ],
    }


def main() -> int:
    ranked = _load_json(RANKED_PATH).get("ranked_candidates") or []
    approved = _load_json(APPROVED_OVERRIDE)
    OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)

    carry_manifests: list[dict] = []
    rotation_manifests: list[dict] = []

    carry_rank = 0
    rotation_rank = 0
    for row in ranked:
        family = row["family"]
        metrics = row["metrics"]
        if family == "carry" and carry_rank < 3:
            carry_rank += 1
            override = _carry_override(approved, metrics, rank=carry_rank)
            path = OVERRIDE_DIR / f"strategy_override.carry_top{carry_rank}.json"
            path.write_text(json.dumps(override, indent=2, ensure_ascii=False), encoding="utf-8")
            carry_manifests.append(
                {
                    "rank": carry_rank,
                    "path": str(path),
                    "label": row["summary"],
                    "score": row["score"],
                }
            )
        if family == "rotation" and rotation_rank < 2:
            rotation_rank += 1
            bundle = _rotation_review_bundle(metrics, rank=rotation_rank)
            path = OVERRIDE_DIR / f"rotation_review_top{rotation_rank}.json"
            path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
            rotation_manifests.append(
                {
                    "rank": rotation_rank,
                    "path": str(path),
                    "label": row["summary"],
                    "score": row["score"],
                }
            )
        if carry_rank >= 3 and rotation_rank >= 2:
            break

    payload = {
        "generated_by": "strategy_execution_bundle",
        "source": str(RANKED_PATH),
        "carry_manifests": carry_manifests,
        "rotation_manifests": rotation_manifests,
    }
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["# Strategy Execution Bundle", "", "## Carry Overrides"]
    for item in carry_manifests:
        lines.append(f"- top{item['rank']}: `{item['label']}` -> `{item['path']}` score={item['score']:.2f}")
    lines.extend(["", "## Rotation Review Bundles"])
    for item in rotation_manifests:
        lines.append(f"- top{item['rank']}: `{item['label']}` -> `{item['path']}` score={item['score']:.2f}")
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 100)
    print("STRATEGY EXECUTION BUNDLE")
    print("=" * 100)
    print(f"saved_json={OUTPUT_JSON}")
    print(f"saved_md={OUTPUT_MD}")
    print(f"carry_manifests={len(carry_manifests)} rotation_manifests={len(rotation_manifests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
