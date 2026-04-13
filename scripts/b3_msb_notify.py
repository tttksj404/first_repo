"""B3 MSB 재최적화 텔레그램 알림."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quant_binance.telegram_notify import send_telegram_message


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", required=True, choices=["PASS", "FAIL", "SKIP"])
    parser.add_argument("--reason", required=True)
    parser.add_argument("--details", default="")
    args = parser.parse_args()

    emoji = {"PASS": "[OK]", "FAIL": "[WARN]", "SKIP": "[INFO]"}
    header = f"{emoji.get(args.status, '')} B3 MSB Reoptimize: {args.status}"
    body = f"{header}\n{args.reason}"
    if args.details:
        body += f"\n---\n{args.details}"

    result = send_telegram_message(body)
    print(f"Telegram: {result}")


if __name__ == "__main__":
    main()
