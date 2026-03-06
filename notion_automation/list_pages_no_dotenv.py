import requests
import json
import os
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def list_pages():
    url = "https://api.notion.com/v1/search"
    payload = {
        "filter": {"property": "object", "value": "page"},
        "sort": {"direction": "descending", "timestamp": "last_edited_time"}
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        results = response.json().get("results", [])
        for page in results:
            title = "Untitled"
            properties = page.get("properties", {})
            for k, v in properties.items():
                if v.get("type") == "title":
                    title_list = v.get("title", [])
                    if title_list: title = title_list[0].get("plain_text", "Untitled")
                    break
            print(f"Title: {title}, ID: {page['id']}")
    else:
        print(f"Error: {response.status_code}, {response.text}")

if __name__ == "__main__":
    list_pages()
