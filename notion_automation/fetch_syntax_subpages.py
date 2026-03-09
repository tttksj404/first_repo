import requests
import json
import os
import time

TOKEN = os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_blocks(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    all_blocks = []
    has_more = True
    next_cursor = None
    
    while has_more:
        params = {"page_size": 100}
        if next_cursor: params["start_cursor"] = next_cursor
        
        res = requests.get(url, headers=HEADERS, params=params)
        if res.status_code != 200:
            print(f"Error fetching {block_id}: {res.text}")
            break
        
        data = res.json()
        all_blocks.extend(data.get("results", []))
        has_more = data.get("has_more")
        next_cursor = data.get("next_cursor")
        time.sleep(0.3)
    return all_blocks

# 파이썬 문법 page ID: 2ebeacc8-175a-803e-98e8-d832509624c1
syntax_page_id = "2ebeacc8-175a-803e-98e8-d832509624c1"
print(f"Fetching children of '파이썬 문법' ({syntax_page_id})...")
children = get_blocks(syntax_page_id)

with open("python_syntax_children.json", "w", encoding="utf-8") as f:
    json.dump(children, f, ensure_ascii=False, indent=2)

for c in children:
    if c["type"] == "child_page":
        print(f"Found subpage: {c['child_page']['title']} ({c['id']})")
