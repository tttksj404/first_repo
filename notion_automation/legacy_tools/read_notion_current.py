# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from notion_automation.core.notion_env import get_notion_token
import requests
import json
TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_page_blocks(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    response = requests.get(url, headers=HEADERS)
    return response.json().get("results", [])

if __name__ == "__main__":
    # DFS/BFS ?섏씠吏 ID
    dfs_bfs_id = "2f0eacc8-175a-805c-85b2-dca59899d3d8"
    blocks = get_page_blocks(dfs_bfs_id)
    
    print(f"--- Current Content of DFS/BFS Page ---")
    for block in blocks:
        b_type = block['type']
        content = block.get(b_type, {})
        text_list = content.get('rich_text', [])
        if text_list:
            print(f"[{b_type}] {text_list[0].get('plain_text', '')}")
        else:
            print(f"[{b_type}] (No Text)")



