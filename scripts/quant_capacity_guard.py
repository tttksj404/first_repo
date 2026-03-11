from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path("/Users/tttksj/first_repo")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_binance.promotion import build_strategy_proposal, proposal_paths
from quant_binance.telegram_notify import send_telegram_message


def main() -> int:
    usage = shutil.disk_usage(ROOT)
    free_ratio = usage.free / usage.total if usage.total else 0.0
    if free_ratio >= 0.20:
        print(json.dumps({"status": "healthy", "free_ratio": round(free_ratio, 6)}, indent=2, sort_keys=True))
        return 0

    proposal = build_strategy_proposal(base_dir="quant_runtime")
    paths = proposal_paths("quant_runtime")
    message = (
        f"[Quant Guard]\\n"
        f"디스크 여유가 20% 미만입니다.\\n"
        f"free_ratio={free_ratio:.4f}\\n"
        f"candidate={proposal.get('candidate_name')}\\n"
        f"objective_score={proposal.get('objective_score')}\\n"
        f"pending={paths['pending']}\\n"
        f"승인: /approve\\n"
        f"거절: /reject"
    )
    send_result = send_telegram_message(message)
    print(
        json.dumps(
            {
                "status": "reported",
                "free_ratio": round(free_ratio, 6),
                "proposal": proposal,
                "telegram": send_result,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
