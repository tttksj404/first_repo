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

def verify():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    res = requests.get(url, headers=HEADERS)
    blocks = res.json().get("results", [])
    
    found = False
    for i, b in enumerate(blocks):
        b_type = b['type']
        if b_type == 'heading_1':
            text = b['heading_1']['rich_text'][0]['plain_text']
            if '빙산' in text:
                found = True
                print(f"--- SUCCESS: Found Heading at index {i} ---")
                print(f"Title: {text}")
                
                # Check next 10 blocks for the code
                for j in range(1, 11):
                    if i+j < len(blocks):
                        nb = blocks[i+j]
                        if nb['type'] == 'code':
                            code_text = nb['code']['rich_text'][0]['plain_text']
                            print(f"--- SUCCESS: Found Code Block at index {i+j} ---")
                            print(f"Code Preview (first 100 chars): {code_text[:100].replace('
', ' ')}")
                            print(f"Contains comments: {'#' in code_text or "'''" in code_text}")
                            return True
                break
                
    if not found:
        print("--- FAILURE: '빙산' problem NOT FOUND on the page ---")
    return False

if __name__ == "__main__":
    verify()
