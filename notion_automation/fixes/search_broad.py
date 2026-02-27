import requests
import json


import os

def _get_notion_token():
    # Try multiple paths to find notion_key.txt
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(current_dir, 'notion_key.txt'),
        os.path.join(current_dir, '..', 'core', 'notion_key.txt'),
        os.path.join(current_dir, 'core', 'notion_key.txt'),
        os.path.join(os.getcwd(), 'notion_automation', 'core', 'notion_key.txt')
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                token = f.read().strip()
                if token: return token
    return os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")

NOTION_TOKEN = _get_notion_token()
HEADERS = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Notion-Version': '2022-06-28'
}

def search_broad(query):
    res = requests.post('https://api.notion.com/v1/search', headers=HEADERS, json={'query': query})
    results = res.json().get('results', [])
    for page in results:
        title_list = page.get('properties', {}).get('title', {}).get('title', [])
        if not title_list and 'Name' in page.get('properties', {}):
            title_list = page['properties']['Name'].get('title', [])
        if title_list:
            print(f"[{query}] ID: {page['id']}, Title: {title_list[0]['plain_text']}")

if __name__ == "__main__":
    search_broad("코테")
    search_broad("삼성")
    search_broad("A형")
