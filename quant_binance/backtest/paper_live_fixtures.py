from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from quant_binance.data.state import SymbolMarketState, TopOfBook
from quant_binance.features.primitive import FeatureHistoryContext, PrimitiveInputs


@dataclass(frozen=True)
class PaperLiveCycle:
    decision_time: datetime
    symbol: str
    state: SymbolMarketState
    primitive_inputs: PrimitiveInputs
    history: FeatureHistoryContext


def load_paper_live_cycles(path: str | Path) -> list[PaperLiveCycle]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cycles: list[PaperLiveCycle] = []
    for item in payload["cycles"]:
        decision_time = datetime.fromisoformat(item["decision_time"])
        state_payload = item["state"]
        top = state_payload["top_of_book"]
        state = SymbolMarketState(
            symbol=item["symbol"],
            top_of_book=TopOfBook(
                bid_price=top["bid_price"],
                bid_qty=top["bid_qty"],
                ask_price=top["ask_price"],
                ask_qty=top["ask_qty"],
                updated_at=datetime.fromisoformat(top["updated_at"]),
            ),
            last_trade_price=state_payload["last_trade_price"],
            funding_rate=state_payload["funding_rate"],
            open_interest=state_payload["open_interest"],
            basis_bps=state_payload["basis_bps"],
            last_update_time=datetime.fromisoformat(state_payload["last_update_time"]),
        )
        cycles.append(
            PaperLiveCycle(
                decision_time=decision_time,
                symbol=item["symbol"],
                state=state,
                primitive_inputs=PrimitiveInputs(**item["primitive_inputs"]),
                history=FeatureHistoryContext(**item["history"]),
            )
        )
    return cycles
