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
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PAGE_ID = "2f0eacc8-175a-805c-85b2-dca59899d3d8"

def find_all_codes():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    has_more = True
    start_cursor = None
    all_blocks = []

    while has_more:
        params = {"start_cursor": start_cursor} if start_cursor else {}
        res = requests.get(url, headers=HEADERS, params=params)
        data = res.json()
        all_blocks.extend(data.get('results', []))
        has_more = data.get('has_more', False)
        start_cursor = data.get('next_cursor')

    prob_ids = ["1260", "2178", "2606", "2667", "2644", "7569", "1697", "5014", "2468", "1926"]
    
    for i, b in enumerate(all_blocks):
        if b['type'] == 'heading_2':
            text = b['heading_2']['rich_text'][0]['plain_text'] if b['heading_2']['rich_text'] else ""
            for pid in prob_ids:
                if pid in text:
                    # Find the code block
                    for j in range(i+1, min(i+5, len(all_blocks))):
                        if all_blocks[j]['type'] == 'code':
                            print(f"{pid}: {all_blocks[j]['id']}")
                            break

if __name__ == "__main__":
    find_all_codes()
