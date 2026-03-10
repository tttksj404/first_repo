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
        ("BFS 2178", "31beacc8-175a-8150-8859-e5dd986c528c"),
        ("Ungrouped 2178", "318eacc8-175a-816f-9ad0-dcc1f05df53e")
    ]
    for name, pid in pages:
        print(f"{name} ({pid}): {get_block_count(pid)} blocks")

if __name__ == "__main__":
    main()
