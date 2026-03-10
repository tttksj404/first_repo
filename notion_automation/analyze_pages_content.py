import requests
import json
import time
from notion_automation.core.notion_env import get_notion_token

NOTION_TOKEN = get_notion_token()
NOTION_VERSION = "2022-06-28"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json"
}

def get_page_content(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        blocks = response.json().get("results", [])
        return blocks
    else:
        print(f"Failed to get content for {page_id}: {response.text}")
        return []

def summarize_blocks(blocks):
    summary = []
    for b in blocks:
        b_type = b["type"]
        if b_type.startswith("heading"):
            text = b[b_type]["rich_text"][0]["plain_text"] if b[b_type]["rich_text"] else "Empty Heading"
            summary.append(f"[{b_type}] {text}")
        elif b_type == "paragraph":
            if b[b_type]["rich_text"]:
                text = b[b_type]["rich_text"][0]["plain_text"]
                if len(text) > 30: text = text[:30] + "..."
                summary.append(f"[p] {text}")
        elif b_type == "child_page":
            summary.append(f"[Page] {b[b_type]['title']}")
    return summary

def main():
    pages = [
        ("재귀&백트래킹 (Parent)", "2f0eacc8-175a-8072-8e4b-e298edcb69c5"),
        ("마스터북 (New)", "31feacc8-175a-815c-ab4b-cc5da3b4d039"),
        ("DFS & 백트래킹 극한정복", "31beacc8-175a-813c-ba9b-c0ff8e8d5d98"),
        ("깊이 우선 탐색 (Old 1)", "31beacc8-175a-81db-acda-fa02ac631576"),
        ("깊이 우선 탐색 (Old 2)", "319eacc8-175a-81e0-9669-f9661759d4f0")
    ]
    
    report = {}
    for name, pid in pages:
        print(f"Analyzing {name}...")
        blocks = get_page_content(pid)
        report[name] = summarize_blocks(blocks)
        time.sleep(0.5)
        
    with open("notion_automation/notion_content_summary.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print("Analysis complete. Summary saved to notion_automation/notion_content_summary.json")

if __name__ == "__main__":
    main()
