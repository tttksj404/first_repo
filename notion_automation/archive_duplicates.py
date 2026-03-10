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

def archive_page(page_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    res = requests.patch(url, headers=HEADERS, json={"archived": True})
    if res.status_code == 200:
        print(f"Successfully archived page {page_id}")
    else:
        print(f"Failed to archive page {page_id}: {res.text}")

def main():
    pages_to_archive = [
        "31eeacc8-175a-8122-bc26-ca316b8f2c44", # Master 2
        "31eeacc8-175a-81f0-97a1-e84a739c4b26", # Master 3
        "319eacc8-175a-81e0-9669-f9661759d4f0"  # Old DFS 2
    ]
    
    for pid in pages_to_archive:
        archive_page(pid)
        time.sleep(0.5)

if __name__ == "__main__":
    main()
