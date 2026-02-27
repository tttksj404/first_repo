import requests
import json
import time
import os

# 1. API Configuration

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
PAGE_ID = "314eacc8175a817c8fa6c89fd1e36a66"
DATA_FILE = os.path.join(os.path.dirname(__file__), 'leet_detailed_content.json')

def append_data():
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        blocks = json.load(f)

    print(f"START: Appending {len(blocks)} detailed blocks...")
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    
    # Send in chunks of 3 for safety
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        res = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if res.status_code == 200:
            print(f"SUCCESS: Chunk {i//3 + 1} appended.")
        else:
            print(f"FAILED: {res.status_code} - {res.text}")
        time.sleep(1)

    print("ALL DETAILED CONTENT APPENDED.")

if __name__ == "__main__":
    append_data()
