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
PAGE_ID = '2f0eacc8-175a-805c-85b2-dca59899d3d8'
HEADERS = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Notion-Version': '2022-06-28'
}

def verify_last():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    params = {"page_size": 100}
    all_blocks = []
    
    while True:
        res = requests.get(url, headers=HEADERS, params=params)
        data = res.json()
        blocks = data.get('results', [])
        all_blocks.extend(blocks)
        if not data.get('has_more'):
            break
        params['start_cursor'] = data.get('next_cursor')
    
    print("Total blocks on page:", len(all_blocks))
    
    # Check the last 15 blocks
    print("--- LAST 15 BLOCKS ---")
    for i in range(max(0, len(all_blocks)-15), len(all_blocks)):
        b = all_blocks[i]
        b_type = b['type']
        text = ""
        if b_type in b and 'rich_text' in b[b_type]:
            rt = b[b_type]['rich_text']
            if rt:
                text = rt[0]['plain_text'][:50]
        print(f"[{i}] {b_type}: {text}")

if __name__ == "__main__":
    verify_last()
