import requests
import time
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
DFS_BFS_PAGE_ID = '2f0eacc8-175a-805c-85b2-dca59899d3d8'
HEADERS = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Notion-Version': '2022-06-28'
}

def clean_dfs_bfs():
    url = f"https://api.notion.com/v1/blocks/{DFS_BFS_PAGE_ID}/children"
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

    # Find where "📍 [Samsung A] 기출 분석" starts
    start_idx = -1
    for i, b in enumerate(all_blocks):
        if b['type'] == 'heading_1':
            rt = b['heading_1']['rich_text']
            if rt and '기출 분석' in rt[0]['plain_text']:
                start_idx = i
                break
    
    if start_idx != -1:
        print(f"Deleting blocks from index {start_idx} onwards...")
        for b in all_blocks[start_idx:]:
            requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
            time.sleep(0.1)
        print("Cleanup successful.")
    else:
        print("Could not find the target section to delete.")

if __name__ == "__main__":
    clean_dfs_bfs()
