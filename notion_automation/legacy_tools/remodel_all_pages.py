# -*- coding: utf-8 -*-
import sys
import time
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def get_child_pages(parent_id):
    url = f"https://api.notion.com/v1/blocks/{parent_id}/children"
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    data = response.json()
    return [b["id"] for b in data.get("results", []) if b.get("type") == "child_page"]


def insert_elements(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    blocks = response.json().get("results", [])
    if not blocks:
        return

    first_id = blocks[0]["id"]

    top_blocks = [
        {"object": "block", "type": "table_of_contents", "table_of_contents": {}},
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"text": {"content": "Review top-to-bottom, then use summary at the end."}}],
                "icon": {"emoji": "📘"},
            },
        },
        {"object": "block", "type": "divider", "divider": {}},
    ]
    top_res = requests.patch(url, json={"children": top_blocks, "after": first_id}, headers=HEADERS, timeout=20)
    top_res.raise_for_status()

    bottom_blocks = [
        {"object": "block", "type": "divider", "divider": {}},
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"text": {"content": "Summary and practical tips"}}]},
        },
        {
            "object": "block",
            "type": "quote",
            "quote": {
                "rich_text": [
                    {
                        "text": {
                            "content": (
                                "- Design logic first with comments.\n"
                                "- Check edge cases early.\n"
                                "- Pick the data structure that matches constraints."
                            )
                        }
                    }
                ]
            },
        },
    ]
    bottom_res = requests.patch(url, json={"children": bottom_blocks}, headers=HEADERS, timeout=20)
    bottom_res.raise_for_status()
    print(f"Refined: {page_id}")


if __name__ == "__main__":
    parent_id = "2e7eacc8-175a-8035-8d30-ca6bf5e1c524"
    children = get_child_pages(parent_id)
    for child in children:
        insert_elements(child)
        time.sleep(1)
    print("All pages refined successfully without any deletion.")
