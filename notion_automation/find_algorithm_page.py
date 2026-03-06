import requests
import os
from notion_automation.core.notion_env import get_notion_token

NOTION_TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def list_pages():
    url = "https://api.notion.com/v1/search"
    payload = {
        "filter": {"property": "object", "value": "page"},
        "query": "Algorithm"
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        results = response.json().get("results", [])
        for page in results:
            title = "Untitled"
            properties = page.get("properties", {})
            # Handle both database page titles and normal page titles
            if "title" in properties:
                title_list = properties["title"].get("title", [])
                if title_list: title = title_list[0].get("plain_text", "Untitled")
            elif "Name" in properties:
                name_list = properties["Name"].get("title", [])
                if name_list: title = name_list[0].get("plain_text", "Untitled")
            
            print(f"Title: {title}, ID: {page['id']}")
    else:
        print(f"Error: {response.status_code}, {response.text}")

if __name__ == "__main__":
    list_pages()
