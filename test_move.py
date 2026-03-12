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

def create_page(title, parent_page_id):
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"page_id": parent_page_id},
        "properties": {
            "title": [{"text": {"content": title}}]
        }
    }
    resp = requests.post(url, headers=HEADERS, json=payload)
    if resp.status_code == 200:
        return resp.json()["id"]
    return None

def move_page(page_id, new_parent_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"parent": {"page_id": new_parent_id}}
    resp = requests.patch(url, headers=HEADERS, json=payload)
    print(f"Move response {resp.status_code}: {resp.text}")
    return resp.status_code == 200

def archive_page(page_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    resp = requests.patch(url, headers=HEADERS, json={"archived": True})
    return resp.status_code == 200

root_id = "231eacc8-175a-80b6-b30b-e061e8f5a3c5"
dest_id = "8938fced-ff81-4868-9e97-96e01212b875" # another root

print("Testing create...")
new_id = create_page("Test Page To Be Moved", root_id)
print(f"Created: {new_id}")

if new_id:
    print("Testing move...")
    success_move = move_page(new_id, dest_id)
    print(f"Moved: {success_move}")
    
    print("Testing archive...")
    success_archive = archive_page(new_id)
    print(f"Archived: {success_archive}")
