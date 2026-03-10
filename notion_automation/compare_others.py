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

def get_block_count(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        return len(res.json().get("results", []))
    return 0

def main():
    pages = [
        ("BT 1759", "31beacc8-175a-814f-b848-c84b74984e09"),
        ("Ungrouped 1759", "318eacc8-175a-8135-8150-e45ae825336b"),
        ("TS 14567", "31beacc8-175a-816b-8379-facefbe8206e"),
        ("Ungrouped 14567", "318eacc8-175a-8126-abe6-da1a6c08872c")
    ]
    for name, pid in pages:
        print(f"{name} ({pid}): {get_block_count(pid)} blocks")

if __name__ == "__main__":
    main()
