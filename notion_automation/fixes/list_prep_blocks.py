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
PAGE_ID = '303eacc8-175a-80a3-9154-f7a7acee7c80'
HEADERS = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Notion-Version': '2022-06-28'
}

def list_blocks():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    res = requests.get(url, headers=HEADERS)
    blocks = res.json().get('results', [])
    for b in blocks:
        b_type = b['type']
        content = ""
        if b_type == 'child_page':
            content = b['child_page']['title']
        elif b_type in ['heading_1', 'heading_2', 'heading_3']:
            rt = b[b_type]['rich_text']
            content = rt[0]['plain_text'] if rt else ""
        print(f"[{b_type}] {content}")

if __name__ == "__main__":
    list_blocks()
