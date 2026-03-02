import requests
import json
import os

def _get_notion_token():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(current_dir, 'notion_key.txt'),
        os.path.join(os.getcwd(), 'notion_automation', 'core', 'notion_key.txt')
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return f.read().strip()
    return os.getenv("NOTION_TOKEN")

NOTION_TOKEN = _get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

DATABASE_ID = "314eacc8-175a-8100-b638-fdfe053da235"

def inspect_db():
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        db_data = res.json()
        print(json.dumps(db_data['properties'], indent=2, ensure_ascii=False))
    else:
        print(f"Error: {res.text}")

if __name__ == '__main__':
    inspect_db()
