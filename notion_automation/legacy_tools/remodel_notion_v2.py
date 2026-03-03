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


def delete_blocks(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    for block in response.json().get("results", []):
        del_url = f"https://api.notion.com/v1/blocks/{block['id']}"
        del_res = requests.delete(del_url, headers=HEADERS, timeout=20)
        del_res.raise_for_status()


def append_blocks(page_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    response = requests.patch(url, json={"children": blocks}, headers=HEADERS, timeout=20)
    response.raise_for_status()


REMODELED_CONTENT = [
    {
        "object": "block",
        "type": "heading_1",
        "heading_1": {"rich_text": [{"text": {"content": "DFS and BFS Master Guide"}}]},
    },
    {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"text": {"content": "Traversal strategy matters as much as visiting nodes."}}],
            "icon": {"emoji": "🧭"},
        },
    },
    {"object": "block", "type": "divider", "divider": {}},
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"text": {"content": "1) Core concepts"}}]},
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"text": {"content": "Use visited checks to prevent cycles and duplicate work."}}]
        },
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"text": {"content": "2) DFS pattern"}}]},
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
                            "def dfs(node):\n"
                            "    visited[node] = True\n"
                            "    for nxt in graph[node]:\n"
                            "        if not visited[nxt]:\n"
                            "            dfs(nxt)"
                        )
                    }
                }
            ],
        },
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"text": {"content": "3) BFS pattern"}}]},
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
                            "from collections import deque\n"
                            "q = deque([start])\n"
                            "visited[start] = True\n"
                            "while q:\n"
                            "    cur = q.popleft()\n"
                            "    for nxt in graph[cur]:\n"
                            "        if not visited[nxt]:\n"
                            "            visited[nxt] = True\n"
                            "            q.append(nxt)"
                        )
                    }
                }
            ],
        },
    },
]


if __name__ == "__main__":
    page_id = "2f0eacc8-175a-805c-85b2-dca59899d3d8"
    print("Redesigning the page with improved layout...")
    delete_blocks(page_id)
    append_blocks(page_id, REMODELED_CONTENT)
    print("Remodeling complete.")
