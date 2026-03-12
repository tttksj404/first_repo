import requests
import json
import os
import sys
import time

sys.path.append(os.getcwd())
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def move_page(page_id, new_parent_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"parent": {"page_id": new_parent_id}}
    resp = requests.patch(url, headers=HEADERS, json=payload)
    return resp.status_code == 200

def archive_page(page_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    resp = requests.patch(url, headers=HEADERS, json={"archived": True})
    return resp.status_code == 200

def merge_and_clean():
    with open("hubs.json", "r") as f:
        hubs = json.load(f)
    
    with open("duplicate_analysis.json", "r", encoding="utf-8") as f:
        dups = json.load(f)

    # 1. Archive Duplicates (Keeping only the best ones)
    for title, versions in dups.items():
        # Sort by block_count descending to keep the most content-rich version
        versions.sort(key=lambda x: x["block_count"], reverse=True)
        master = versions[0]
        to_archive = versions[1:]
        
        print(f"Keeping master for '{title}': {master['id']}")
        for v in to_archive:
            print(f"Archiving duplicate: {v['id']}")
            archive_page(v["id"])
            time.sleep(0.5)

    # 2. Move Master Pages to Hubs
    # Define movement map based on titles
    with open("notion_tree.json", "r", encoding="utf-8") as f:
        tree_data = json.load(f)
    
    page_map = tree_data["page_map"]
    
    for pid, info in page_map.items():
        title = info["title"]
        target_hub = None
        
        # Avoid moving the hubs themselves
        if pid in [hubs["main"], hubs["algo"], hubs["leet"], hubs["dev"]]:
            continue
            
        if "삼성 A형" in title or "알고리즘" in title or "Step" in title or "BFS" in title or "DFS" in title or "백트래킹" in title or "DP" in title or "코테" in title:
            target_hub = hubs["algo"]
        elif "LEET" in title or "추리" in title or "언어이해" in title:
            target_hub = hubs["leet"]
        elif "ssafy" in title.lower() or "파이썬" in title or "AI" in title or "데이터 분석" in title:
            target_hub = hubs["dev"]
            
        if target_hub:
            print(f"Moving '{title}' -> Hub")
            move_page(pid, target_hub)
            time.sleep(0.3)

if __name__ == "__main__":
    merge_and_clean()
