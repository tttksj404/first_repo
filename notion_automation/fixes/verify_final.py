import requests
import json
import sys


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

def verify_notion_content():
    print(f"--- Verifying content on page {PAGE_ID} ---")
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    res = requests.get(url, headers=HEADERS)
    if res.status_code != 200:
        print(f"Error fetching page: {res.text}")
        return

    blocks = res.json().get("results", [])
    found_iceberg = False
    
    for i, block in enumerate(blocks):
        block_type = block['type']
        content = ""
        
        if block_type == 'heading_1':
            content = block['heading_1']['rich_text'][0]['plain_text'] if block['heading_1']['rich_text'] else ""
        elif block_type == 'heading_2':
            content = block['heading_2']['rich_text'][0]['plain_text'] if block['heading_2']['rich_text'] else ""
        elif block_type == 'code':
            code_text = block['code']['rich_text'][0]['plain_text'] if block['code']['rich_text'] else ""
            content = f"[CODE BLOCK: {code_text[:50]}...]"
            
        if "빙산" in content:
            found_iceberg = True
            print(f"FOUND at index {i}: Type: {block_type}, Content: {content}")
            
            # If it's a heading, look at the next few blocks to verify details
            if block_type == 'heading_1':
                print("--- Inspecting detail blocks ---")
                for j in range(1, 10):
                    if i + j < len(blocks):
                        next_block = blocks[i+j]
                        ntype = next_block['type']
                        if ntype == 'code':
                            code_full = next_block['code']['rich_text'][0]['plain_text']
                            has_comments = "#" in code_full or "'''" in code_full
                            print(f"  [{j}] Code Block Found. Has comments: {has_comments}")
                            if has_comments:
                                print(f"  First 100 chars of code: {code_full[:100].replace('
', ' ')}")
                        elif ntype == 'quote':
                            q_text = next_block['quote']['rich_text'][0]['plain_text']
                            print(f"  [{j}] Quote: {q_text[:50]}...")
                        else:
                            print(f"  [{j}] {ntype}")
                break
                
    if not found_iceberg:
        print("RESULT: '빙산' content NOT FOUND on this page.")
    else:
        print("RESULT: '빙산' content FOUND and verified.")

if __name__ == "__main__":
    verify_notion_content()
