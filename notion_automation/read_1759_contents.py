import requests
import json
import time
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def read_full_page(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        blocks = res.json().get("results", [])
        summary = []
        for b in blocks:
            b_type = b["type"]
            text = ""
            if b_type.startswith("heading") or b_type == "paragraph":
                text = "".join([t["plain_text"] for t in b[b_type]["rich_text"]]) if b[b_type]["rich_text"] else ""
                summary.append(f"[{b_type}] {text[:50]}")
        return summary
    return []

def main():
    print("Content of BT 1759 (22 blocks):")
    print(json.dumps(read_full_page("31beacc8-175a-814f-b848-c84b74984e09"), indent=2, ensure_ascii=False))
    print("\nContent of Ungrouped 1759 (54 blocks):")
    print(json.dumps(read_full_page("318eacc8-175a-8135-8150-e45ae825336b"), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
