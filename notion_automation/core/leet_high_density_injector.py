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
PAGE_ID = "314eacc8175a819cbf7cc56ed28d50cf"
DATA_FILE = os.path.join(os.path.dirname(__file__), 'leet_blueprint.json')

def inject_data():
    if not os.path.exists(DATA_FILE):
        print("ERROR: JSON data file not found.")
        return

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        content_blocks = json.load(f)

    print(f"START: Injecting {len(content_blocks)} high-density blocks...")
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    
    for i in range(0, len(content_blocks), 3):
        chunk = content_blocks[i:i+3]
        res = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if res.status_code == 200:
            print(f"SUCCESS: Chunk {i//3 + 1} deployed.")
        else:
            print(f"FAILED: {res.status_code} - {res.text}")
        time.sleep(1)

    print("ALL DATA INJECTED SUCCESSFULLY.")

if __name__ == "__main__":
    inject_data()
