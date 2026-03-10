import requests
import json
import time
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_page_title(page_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        props = res.json().get("properties", {})
        for k, v in props.items():
            if v.get("type") == "title":
                return v.get("title", [{}])[0].get("plain_text", "Untitled")
    return "Unknown"

def main():
    ids = [
        "31beacc8-175a-8150-8859-e5dd986c528c",
        "319eacc8-175a-81ac-aecf-dbc7aacebc69",
        "318eacc8-175a-816f-9ad0-dcc1f05df53e"
    ]
    for pid in ids:
        print(f"ID: {pid}, Title: {get_page_title(pid)}")

if __name__ == "__main__":
    main()
