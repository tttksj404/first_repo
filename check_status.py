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

def list_all_pages_including_archived():
    url = "https://api.notion.com/v1/search"
    # Notion Search API doesn't have a direct 'archived' filter, 
    # but we can check the 'archived' property of each result.
    # However, it usually doesn't return archived pages unless they are in the workspace.
    # Let's just list everything we can find.
    payload = {
        "filter": {"property": "object", "value": "page"}
    }
    resp = requests.post(url, headers=HEADERS, json=payload)
    if resp.status_code == 200:
        results = resp.json().get("results", [])
        for p in results:
            title = "Untitled"
            props = p.get("properties", {})
            for k, v in props.items():
                if v.get("type") == "title":
                    title_list = v.get("title", [])
                    if title_list: title = title_list[0].get("plain_text", "Untitled")
            print(f"Title: {title}, ID: {p['id']}, Archived: {p['archived']}, Parent: {p['parent']}")
    else:
        print(f"Error: {resp.status_code}, {resp.text}")

if __name__ == "__main__":
    list_all_pages_including_archived()
