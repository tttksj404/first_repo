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

def get_blocks(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        return res.json().get("results", [])
    return []

def main():
    strategy_page_id = "31beacc8-175a-813c-ba9b-c0ff8e8d5d98"
    blocks = get_blocks(strategy_page_id)
    for b in blocks:
        b_type = b["type"]
        text = ""
        if b_type.startswith("heading"):
            text = b[b_type]["rich_text"][0]["plain_text"] if b[b_type]["rich_text"] else ""
        elif b_type == "paragraph":
            text = b[b_type]["rich_text"][0]["plain_text"] if b[b_type]["rich_text"] else ""
        print(f"ID: {b['id']}, Type: {b_type}, Text: {text}")

if __name__ == "__main__":
    main()
