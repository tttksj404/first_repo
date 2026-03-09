import requests
import os
import json
import time

TOKEN = os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
MASTER_PAGE_ID = "31eeacc8-175a-81f0-97a1-e84a739c4b26"

def api_request(method, path, payload=None):
    url = f"https://api.notion.com/v1{path}"
    res = requests.request(method, url, headers=HEADERS, json=payload)
    res.raise_for_status()
    return res.json()

def append_blocks(block_id, blocks):
    for i in range(0, len(blocks), 50):
        chunk = blocks[i:i+50]
        api_request("PATCH", f"/blocks/{block_id}/children", {"children": chunk})
        time.sleep(0.5)

def main():
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
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": f"[{tag}] ({len(p_list)} 문항)"}}]}
        })
        
        for p in p_list:
            # Create a mention/link to the page
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [
                        {
                            "type": "mention",
                            "mention": {"type": "page", "page": {"id": p["id"]}}
                        }
                    ]
                }
            })
            
    print(f"🚀 Appending {len(blocks)} problem links to Masterbook...")
    append_blocks(MASTER_PAGE_ID, blocks)
    print("✅ Problem Bank added!")

if __name__ == "__main__":
    main()
