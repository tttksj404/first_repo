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

def find_all_iceberg():
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
    
    print("Total blocks:", len(all_blocks))
    for i, b in enumerate(all_blocks):
        b_type = b['type']
        full_text = ""
        if b_type in b and 'rich_text' in b[b_type]:
            rt = b[b_type]['rich_text']
            for part in rt:
                full_text += part['plain_text']
        
        if '빙산' in full_text or 'ice_list' in full_text:
            print(f"[{i}] {b_type}: {full_text[:100].strip().replace('
', ' ')}...")

if __name__ == "__main__":
    find_all_iceberg()
