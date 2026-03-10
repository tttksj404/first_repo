import requests
import os
import json
import time
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
# Correct Master Page ID (Master 1)
MASTER_PAGE_ID = "31eeacc8-175a-8183-b982-f39616d86dce"

def api_request(method, path, payload=None):
    url = f"https://api.notion.com/v1{path}"
    res = requests.request(method, url, headers=HEADERS, json=payload)
    if res.status_code != 200:
        print(f"Error {res.status_code}: {res.text}")
        res.raise_for_status()
    return res.json()

def append_blocks(block_id, blocks):
    for i in range(0, len(blocks), 50):
        chunk = blocks[i:i+50]
        api_request("PATCH", f"/blocks/{block_id}/children", {"children": chunk})
        time.sleep(0.5)

def main():
    if not os.path.exists("problem_pages_grouped.json"):
        print("problem_pages_grouped.json not found")
        return
        
    with open("problem_pages_grouped.json", "r", encoding="utf-8") as f:
        grouped = json.load(f)
    
    blocks = []
    blocks.append({"object": "block", "type": "divider", "divider": {}})
    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": "🏛️ 문제 은행 (유형별 실전 분석)"}}]}
    })
    
    for tag, p_list in grouped.items():
        # Remove duplicate IDs within the same tag
        unique_p_list = []
        seen_ids = set()
        for p in p_list:
            if p["id"] not in seen_ids:
                unique_p_list.append(p)
                seen_ids.add(p["id"])
        
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": f"[{tag}] ({len(unique_p_list)} 문항)"}}]}
        })
        
        for p in unique_p_list:
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [
                        {
                            "type": "mention",
                            "mention": {"type": "page", "page": {"id": p["id"]}}
                        },
                        {
                            "type": "text",
                            "text": {"content": f" - {p['title']}"}
                        }
                    ]
                }
            })
            
    print(f"🚀 Appending problem links to Masterbook ({MASTER_PAGE_ID})...")
    append_blocks(MASTER_PAGE_ID, blocks)
    
    # Also append to the Parent Hub
    PARENT_HUB_ID = "2f0eacc8-175a-8072-8e4b-e298edcb69c5"
    print(f"🚀 Appending problem links to Parent Hub ({PARENT_HUB_ID})...")
    append_blocks(PARENT_HUB_ID, blocks)
    
    print("✅ Problem Bank added to both locations!")

if __name__ == "__main__":
    main()
