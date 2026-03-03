# -*- coding: utf-8 -*-
import sys
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


def append_blocks(page_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    response = requests.patch(url, json={"children": blocks}, headers=HEADERS, timeout=20)
    response.raise_for_status()


STUDENT_SUMMARY = [
    {"object": "block", "type": "divider", "divider": {}},
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"text": {"content": "DFS/BFS Summary Guide"}}]},
    },
    {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"text": {"content": "Quick review notes for DFS/BFS."}}],
            "icon": {"emoji": "📘"},
        },
    },
    {
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [{"text": {"content": "1) When to use each"}}]},
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"text": {"content": "Connected components: DFS or BFS"}}]
        },
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"text": {"content": "Shortest path in unweighted graph: BFS"}}]
        },
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"text": {"content": "Exhaustive search: DFS + backtracking"}}]
        },
    },
    {
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [{"text": {"content": "2) Common mistakes"}}]},
    },
    {
        "object": "block",
        "type": "quote",
        "quote": {
            "rich_text": [
                {
                    "text": {
                        "content": (
                            "- Always check boundary conditions.\n"
                            "- Mark visited nodes at the right time.\n"
                            "- Restore state in backtracking."
                        )
                    }
                }
            ]
        },
    },
]


if __name__ == "__main__":
    page_id = "2f0eacc8-175a-805c-85b2-dca59899d3d8"
    append_blocks(page_id, STUDENT_SUMMARY)
    print("Successfully appended the summary guide.")
