import requests
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from notion_automation.core.notion_env import get_notion_token


def main() -> int:
    token = get_notion_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
    }
    response = requests.get("https://api.notion.com/v1/users/me", headers=headers, timeout=20)
    if response.status_code == 200:
        data = response.json()
        name = data.get("name") or data.get("id") or "unknown"
        print(f"Notion connection OK: {name}")
        return 0

    print(f"Notion connection failed: {response.status_code}")
    print(response.text)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

