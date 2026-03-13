import requests
import os
import sys

# Fix encoding for Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def _get_notion_token():
    # Try multiple paths to find notion_key.txt
    paths = [
        'notion_automation/core/notion_key.txt',
        'notion_key.txt',
        'notion_automation/.env.notion'
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if 'NOTION_TOKEN=' in content:
                    return content.split('NOTION_TOKEN=')[1].split('\n')[0].strip().strip('"').strip("'")
                return content
    return os.getenv('NOTION_TOKEN')

NOTION_TOKEN = _get_notion_token()
HEADERS = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Notion-Version': '2022-06-28',
    'Content-Type': 'application/json'
}

def search_notion():
    queries = ['토마토', '쉬운 최단거리', 'DFS와 BFS', '1260', '7576', '14940']
    results = []
    for q in queries:
        try:
            res = requests.post('https://api.notion.com/v1/search', headers=HEADERS, json={'query': q})
            data = res.json()
            if 'results' in data:
                for page in data['results']:
                    if page['object'] == 'page':
                        props = page.get('properties', {})
                        title = 'No Title'
                        for p_name in ['title', 'Name', '이름', '문제명']:
                            if p_name in props and props[p_name].get('title'):
                                if props[p_name]['title']:
                                    title = props[p_name]['title'][0]['plain_text']
                                    break
                        results.append({'id': page['id'], 'title': title, 'query': q})
                        print(f"QUERY: {q} | ID: {page['id']} | TITLE: {title}")
        except Exception as e:
            print(f"Error searching for {q}: {e}")
    return results

if __name__ == "__main__":
    search_notion()
