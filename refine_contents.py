import requests
import json
import os
import sys

sys.path.append(os.getcwd())
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_blocks(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    resp = requests.get(url, headers=HEADERS)
    return resp.json().get("results", []) if resp.status_code == 200 else []

def refine_page(page_id):
    blocks = get_blocks(page_id)
    if not blocks: return
    
    # 1. Insert TOC at the top if not exists
    has_toc = any(b["type"] == "table_of_contents" for b in blocks)
    if not has_toc:
        url = f"https://api.notion.com/v1/blocks/{page_id}/children"
        payload = {"children": [
            {"type": "table_of_contents", "table_of_contents": {"color": "gray"}},
            {"type": "divider", "divider": {}}
        ]}
        # We want this at the TOP. PATCH appends. 
        # Notion doesn't have "prepend" via API easily, but for new/cleaner pages we append.
        # For existing pages, let's just ensure content is structured.
        requests.patch(url, headers=HEADERS, json=payload)

if __name__ == "__main__":
    # Refine the 'Masterbook'
    masterbook_id = "31eeacc8-175a-8183-b982-f39616d86dce"
    refine_page(masterbook_id)
    print(f"Refined Masterbook: {masterbook_id}")
