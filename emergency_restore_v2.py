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
    with open("notion_pages_list.json", "r", encoding="utf-8") as f:
        old_pages = json.load(f)
    
    safe_parent = "231eacc8-175a-80b6-b30b-e061e8f5a3c5" # HOME (메인 대시보드)
    
    for p in old_pages:
        pid = p["id"]
        title = p["title"]
        print(f"Restoring '{title}' ({pid})...")
        
        update_url = f"https://api.notion.com/v1/pages/{pid}"
        payload = {
            "archived": False,
            "parent": {"page_id": safe_parent}
        }
        res = requests.patch(update_url, headers=HEADERS, json=payload)
        if res.status_code == 200:
            print(f"  OK: Restored and moved.")
        else:
            # Try just unarchiving
            res2 = requests.patch(update_url, headers=HEADERS, json={"archived": False})
            if res2.status_code == 200:
                print(f"  OK: Unarchived only.")
            else:
                print(f"  ERR: {res2.status_code} - {res2.text}")
        time.sleep(0.1)

if __name__ == "__main__":
    restore_pages()
