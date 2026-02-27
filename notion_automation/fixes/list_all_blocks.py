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
    'Content-Type': 'application/json',
    'Notion-Version': '2022-06-28'
}

def list_all_blocks():
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
    
    print("Total blocks found:", len(all_blocks))
    for i, b in enumerate(all_blocks):
        b_type = b['type']
        content = ""
        if b_type == 'heading_1':
            content = b['heading_1']['rich_text'][0]['plain_text'] if b['heading_1']['rich_text'] else ""
        elif b_type == 'heading_2':
            content = b['heading_2']['rich_text'][0]['plain_text'] if b['heading_2']['rich_text'] else ""
        
        # Only print '빙산' related or interesting blocks to save output space
        if '빙산' in content:
            print(f"[{i}] {b_type}: {content}")
        elif b_type == 'code':
            rt = b['code']['rich_text']
            if rt and ('빙산' in rt[0]['plain_text'] or 'ice_list' in rt[0]['plain_text']):
                print(f"[{i}] code: [ICEBERG CODE FOUND]")
    
    # Check the last 10 blocks regardless
    print("--- Last 10 blocks ---")
    for i in range(max(0, len(all_blocks)-10), len(all_blocks)):
        b = all_blocks[i]
        b_type = b['type']
        content = ""
        if b_type == 'heading_1':
            content = b['heading_1']['rich_text'][0]['plain_text'] if b['heading_1']['rich_text'] else ""
        print(f"[{i}] {b_type}: {content}")

if __name__ == "__main__":
    list_all_blocks()
