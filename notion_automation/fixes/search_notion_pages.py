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

def search_notion():
    queries = ['백트래킹', '위상 정렬', '그래프', 'A형', 'A-type']
    found_pages = []
    for q in queries:
        res = requests.post('https://api.notion.com/v1/search', headers=HEADERS, json={'query': q})
        results = res.json().get('results', [])
        for page in results:
            if page['object'] == 'page':
                title_list = page.get('properties', {}).get('title', {}).get('title', [])
                if title_list:
                    title = title_list[0]['plain_text']
                    found_pages.append((page['id'], title))
                    print(f"[{q}] ID: {page['id']}, Title: {title}")
    return found_pages

if __name__ == "__main__":
    search_notion()
