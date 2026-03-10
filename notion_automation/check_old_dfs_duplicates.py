import requests
import json
import time
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_blocks(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        return res.json().get("results", [])
    return []

def summarize_page(page_id):
    blocks = get_blocks(page_id)
    summary = []
    for b in blocks:
        b_type = b["type"]
        if b_type.startswith("heading"):
            text = b[b_type]["rich_text"][0]["plain_text"] if b[b_type]["rich_text"] else "Empty"
            summary.append(f"[{b_type}] {text}")
        elif b_type == "paragraph":
             if b[b_type]["rich_text"]:
                text = b[b_type]["rich_text"][0]["plain_text"]
                if "현실 로직" in text or "코딩 변환" in text or "문제" in text:
                    summary.append(f"[p] {text[:50]}")
    return summary

def main():
    old_pages = [
        ("Old 1", "31beacc8-175a-81db-acda-fa02ac631576"),
        ("Old 2", "319eacc8-175a-81e0-9669-f9661759d4f0")
    ]
    
    results = {}
    for name, pid in old_pages:
        results[name] = summarize_page(pid)
        
    print(json.dumps(results, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
