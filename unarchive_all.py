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

def unarchive_everything():
    with open("notion_pages_list.json", "r", encoding="utf-8") as f:
        old_pages = json.load(f)
    
    for p in old_pages:
        pid = p["id"]
        update_url = f"https://api.notion.com/v1/pages/{pid}"
        # Just unarchive, don't move. 
        # If it has an archived parent, we need to find that parent too.
        requests.patch(update_url, headers=HEADERS, json={"archived": False})
        time.sleep(0.1)

if __name__ == "__main__":
    unarchive_everything()
    print("Unarchive pass completed.")
