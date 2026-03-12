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

def restore_pages():
    # 1. Search for EVERYTHING (including things that might be hidden)
    url = "https://api.notion.com/v1/search"
    payload = {
        "filter": {"property": "object", "value": "page"},
        "page_size": 100
    }
    resp = requests.post(url, headers=HEADERS, json=payload)
    if resp.status_code != 200:
        print(f"Search failed: {resp.text}")
        return

    results = resp.json().get("results", [])
    print(f"Found {len(results)} pages in search.")
    
    # Also, we have the IDs from notion_pages_list.json (previous state)
    # Let's try to UNARCHIVE them and move them back to Workspace root or a safe place.
    with open("notion_pages_list.json", "r") as f:
        old_pages = json.load(f)
    
    # Target parent: Workspace root if possible, or just a known page.
    # Since workspace root move via API is tricky, let's move to the HOME page I created.
    safe_parent = "231eacc8-175a-80b6-b30b-e061e8f5a3c5" # HOME (메인 대시보드)
    
    for p in old_pages:
        pid = p["id"]
        title = p["title"]
        print(f"Attempting to restore '{title}' ({pid})...")
        
        # Patch archived: False and move to safe_parent
        update_url = f"https://api.notion.com/v1/pages/{pid}"
        # We try to restore and move in one go
        payload = {
            "archived": False,
            "parent": {"page_id": safe_parent}
        }
        res = requests.patch(update_url, headers=HEADERS, json=payload)
        if res.status_code == 200:
            print(f"Successfully restored and moved '{title}'")
        else:
            # If moving to parent fails, at least try to unarchive
            res2 = requests.patch(update_url, headers=HEADERS, json={"archived": False})
            if res2.status_code == 200:
                print(f"Successfully unarchived '{title}' (couldn't move)")
            else:
                print(f"Failed to restore '{title}': {res2.text}")
        time.sleep(0.2)

if __name__ == "__main__":
    restore_pages()
