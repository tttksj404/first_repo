import requests
import json
from notion_automation.core.notion_env import get_notion_token

NOTION_TOKEN = get_notion_token()
NOTION_VERSION = "2022-06-28"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json"
}

def search_pages(query):
    url = "https://api.notion.com/v1/search"
    payload = {
        "query": query,
        "filter": {"value": "page", "property": "object"}
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        results = response.json().get("results", [])
        for page in results:
            title = page.get("properties", {}).get("title", {}).get("title", [{}])[0].get("plain_text", "N/A")
            print(f"Page Title: {title}, ID: {page['id']}")
    else:
        print(f"Search failed: {response.text}")

if __name__ == "__main__":
    search_pages("백트래킹")
    search_pages("순열")
    search_pages("조합")
    search_pages("부분집합")
