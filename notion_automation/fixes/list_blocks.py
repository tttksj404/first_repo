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

def list_blocks():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    res = requests.get(url, headers=HEADERS)
    data = res.json()
    blocks = data.get('results', [])
    print("Total blocks:", len(blocks))
    for i, b in enumerate(blocks):
        b_type = b['type']
        content = ""
        if b_type == 'heading_1':
            content = b['heading_1']['rich_text'][0]['plain_text'] if b['heading_1']['rich_text'] else ""
        elif b_type == 'heading_2':
            content = b['heading_2']['rich_text'][0]['plain_text'] if b['heading_2']['rich_text'] else ""
        elif b_type == 'paragraph':
            content = b['paragraph']['rich_text'][0]['plain_text'][:30] if b['paragraph']['rich_text'] else ""
        elif b_type == 'code':
            content = "[CODE]"
        
        print(f"[{i}] {b_type}: {content}")

if __name__ == "__main__":
    list_blocks()
