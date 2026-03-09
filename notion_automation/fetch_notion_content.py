import requests
import json
import os
import time

TOKEN = os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_blocks(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    all_blocks = []
    has_more = True
    next_cursor = None
    
    while has_more:
        params = {"page_size": 100}
        if next_cursor: params["start_cursor"] = next_cursor
        
        res = requests.get(url, headers=HEADERS, params=params)
        if res.status_code != 200:
            print(f"Error fetching {block_id}: {res.text}")
            break
        
        data = res.json()
        all_blocks.extend(data.get("results", []))
        has_more = data.get("has_more")
        next_cursor = data.get("next_cursor")
        time.sleep(0.3)
    return all_blocks

page_ids = {
    "weak_points": "318eacc8-175a-8099-b14d-f484fcbb1f18",
    "im_summary_brief": "30beacc8-175a-8073-a52f-cca3d8cc8b63",
    "codex_summary": "1677d48e-73f4-4e05-976d-0da8d115ccf0",
    "backtracking_master": "31eeacc8-175a-812b-b26a-e9d3a185d95e"
}

collected_data = {}
for name, pid in page_ids.items():
    print(f"Fetching {name} ({pid})...")
    collected_data[name] = get_blocks(pid)

with open("notion_consolidation_data.json", "w", encoding="utf-8") as f:
    json.dump(collected_data, f, ensure_ascii=False, indent=2)

print("✅ Data collection complete.")
