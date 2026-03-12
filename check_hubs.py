import requests
import json
import os
import sys

sys.path.append(os.getcwd())
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def check_hub_children(hub_id, name):
    url = f"https://api.notion.com/v1/blocks/{hub_id}/children"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        results = resp.json().get("results", [])
        print(f"--- Children of {name} ({hub_id}) ---")
        for b in results:
            if b["type"] == "child_page":
                print(f"Page: {b['child_page']['title']} ({b['id']})")
            else:
                print(f"Block: {b['type']}")
    else:
        print(f"Error for {name}: {resp.status_code}")

if __name__ == "__main__":
    hubs = {
        "Algo": "321eacc8-175a-81e1-adff-f68460b7221a",
        "LEET": "321eacc8-175a-8118-b4be-dd94bda3e726",
        "Dev": "321eacc8-175a-81b5-8b9c-f9e95b4b4567"
    }
    for name, hid in hubs.items():
        check_hub_children(hid, name)
