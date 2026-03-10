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

def read_full_page(page_id):
    blocks = get_blocks(page_id)
    content = []
    for b in blocks:
        b_type = b["type"]
        if b_type == "paragraph":
            text = "".join([t["plain_text"] for t in b[b_type]["rich_text"]]) if b[b_type]["rich_text"] else ""
            content.append(text)
        elif b_type.startswith("heading"):
            text = "".join([t["plain_text"] for t in b[b_type]["rich_text"]]) if b[b_type]["rich_text"] else ""
            content.append(f"#{text}")
    return "\n".join(content)

def main():
    print(read_full_page("31beacc8-175a-81db-acda-fa02ac631576"))

if __name__ == "__main__":
    main()
