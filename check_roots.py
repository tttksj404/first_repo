import requests
import json
import os
import sys
from pathlib import Path
from collections import defaultdict

sys.path.append(os.getcwd())
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_all_pages():
    pages = []
    has_more = True
    next_cursor = None
    url = "https://api.notion.com/v1/search"
    
    while has_more:
        payload = {
            "filter": {"property": "object", "value": "page"},
            "page_size": 100
        }
        if next_cursor:
            payload["start_cursor"] = next_cursor
            
        resp = requests.post(url, headers=HEADERS, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            pages.extend(data.get("results", []))
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
        else:
            break
    return pages

def analyze():
    pages = get_all_pages()
    root_pages = []
    for p in pages:
        parent = p.get("parent", {})
        if parent.get("type") == "workspace":
            title = "Untitled"
            props = p.get("properties", {})
            for k, v in props.items():
                if v.get("type") == "title":
                    title_list = v.get("title", [])
                    if title_list: title = "".join(t.get("plain_text", "") for t in title_list)
                    break
            root_pages.append({"title": title, "id": p["id"]})
    
    print("Root Pages:")
    for rp in root_pages:
        print(f"- {rp['title']} ({rp['id']})")

if __name__ == "__main__":
    analyze()
