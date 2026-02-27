import requests
import json


import os

def _get_notion_token():
    # Try multiple paths to find notion_key.txt
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(current_dir, 'notion_key.txt'),
        os.path.join(current_dir, '..', 'core', 'notion_key.txt'),
        os.path.join(current_dir, 'core', 'notion_key.txt'),
        os.path.join(os.getcwd(), 'notion_automation', 'core', 'notion_key.txt')
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                token = f.read().strip()
                if token: return token
    return os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")

NOTION_TOKEN = _get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PAGE_ID = "2f0eacc8-175a-805c-85b2-dca59899d3d8"

def inspect_all():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    has_more = True
    start_cursor = None
    all_blocks = []

    while has_more:
        params = {"start_cursor": start_cursor} if start_cursor else {}
        res = requests.get(url, headers=HEADERS, params=params)
        data = res.json()
        all_blocks.extend(data.get('results', []))
        has_more = data.get('has_more', False)
        start_cursor = data.get('next_cursor')

    print(f"Total blocks found: {len(all_blocks)}")
    # Print last 50 blocks to see what's at the bottom
    for i, b in enumerate(all_blocks[-50:]):
        idx = len(all_blocks) - 50 + i
        b_type = b['type']
        content = ""
        if b_type == 'heading_2':
            content = b['heading_2']['rich_text'][0]['plain_text'] if b['heading_2']['rich_text'] else "EMPTY"
        elif b_type == 'code':
            content = "CODE BLOCK"
        print(f"[{idx}] {b_type.upper()}: {content} | ID: {b['id']}")

if __name__ == "__main__":
    inspect_all()
