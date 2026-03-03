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


STUDENT_NOTES = [
    {"object": "block", "type": "divider", "divider": {}},
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"text": {"content": "Greedy Study Notes"}}]},
    },
    {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"text": {"content": "Extra notes from problem-solving practice."}}],
            "icon": {"emoji": "📘"},
        },
    },
    {
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [{"text": {"content": "1) Greedy vs Parametric Search"}}]},
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {
                    "text": {
                        "content": "If condition says at least M, try binary search over answer space."
                    }
                }
            ]
        },
    },
    {
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [{"text": {"content": "2) Efficiency tip"}}]},
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "text": {
                        "content": "Use large units first and combine with modulo operations when possible."
                    }
                }
            ]
        },
    },
    {
        "object": "block",
        "type": "code",
        "code": {
            "language": "python",
            "rich_text": [
                {
                    "text": {
                        "content": (
                            "# Greedy logic example\n"
                            "items.sort(key=lambda x: x[1], reverse=True)\n"
                            "for item in items:\n"
                            "    if capacity >= item[0]:\n"
                            "        capacity -= item[0]\n"
                            "        total_value += item[1]"
                        )
                    }
                }
            ],
        },
    },
]


if __name__ == "__main__":
    page_id = "2feeacc8-175a-80ee-9739-cb395ef4cc64"
    append_blocks(page_id, STUDENT_NOTES)
    print("Appended new insights successfully.")
