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
    return requests.get(url, headers=HEADERS).json().get("results", [])

if __name__ == "__main__":
    page_id = "2f0eacc8-175a-805c-85b2-dca59899d3d8"
    blocks = get_page_blocks(page_id)
    for i, block in enumerate(blocks):
        b_type = block['type']
        text = ""
        if 'rich_text' in block[b_type]:
            text_list = block[b_type]['rich_text']
            if text_list:
                text = text_list[0].get('plain_text', '')
        print(f"Index: {i}, ID: {block['id']}, Type: {b_type}, Content: {text[:30]}...")



