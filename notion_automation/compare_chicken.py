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
        ("Old 1", "31beacc8-175a-81db-acda-fa02ac631576"),
        ("New Samsung A", "319eacc8-175a-81ac-aecf-dbc7aacebc69")
    ]
    for name, pid in pages:
        print(f"{name} ({pid}): {get_block_count(pid)} blocks")

if __name__ == "__main__":
    main()
