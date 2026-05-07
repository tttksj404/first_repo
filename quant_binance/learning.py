from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quant_binance.models import DecisionIntent
from quant_binance.strategy.edge import ConditionalEdgeLookup


@dataclass(frozen=True)
class LearningUpdate:
    observation_count: int
    symbols: tuple[str, ...]
    updated_path: Path


class OnlineEdgeLearner:
    def __init__(self, *, min_observations: int = 5) -> None:
        self.lookup = ConditionalEdgeLookup(min_observations=min_observations)

    def ingest_decisions(
        self,
        decisions: list[DecisionIntent] | tuple[DecisionIntent, ...],
        *,
        realized_return_override_bps: dict[str, float] | None = None,
    ) -> int:
        count = 0
        for decision in decisions:
            if decision.final_mode not in {"spot", "futures"}:
                continue
            realized_bps = (
                realized_return_override_bps.get(decision.decision_id)
                if realized_return_override_bps is not None
                else None
            )
            if realized_bps is None:
                realized_bps = decision.gross_expected_edge_bps
            self.lookup.add_observation(
                symbol=decision.symbol,
                mode=decision.final_mode,
                predictability_score=decision.predictability_score,
                trend_direction=decision.trend_direction or 1,
                forward_return_bps=realized_bps,
            )
            count += 1
        return count

    def export(self, path: str | Path) -> LearningUpdate:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        symbol_rows: dict[str, list[dict[str, Any]]] = {}
        observation_count = 0
        for (symbol, mode, bucket, direction), values in self.lookup._symbol_buckets.items():
            symbol_rows.setdefault(symbol, []).append(
                {
                    "mode": mode,
                    "bucket": bucket,
                    "trend_direction": direction,
                    "observations": values,
                    "median_bps": sorted(values)[len(values) // 2],
                }
            )
            observation_count += len(values)
        output_path.write_text(
            json.dumps(
                {
                    "observation_count": observation_count,
                    "symbols": symbol_rows,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return LearningUpdate(
            observation_count=observation_count,
            symbols=tuple(sorted(symbol_rows.keys())),
            updated_path=output_path,
        )
