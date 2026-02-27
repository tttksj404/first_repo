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
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
DB_ID = "314eacc8-175a-8100-b638-fdfe053da235"

def clean_duplicates():
    # 1. 모든 데이터 조회
    url = f"https://api.notion.com/v1/databases/{DB_ID}/query"
    res = requests.post(url, headers=HEADERS)
    results = res.json().get('results', [])
    
    print(f"🔍 총 {len(results)}개의 항목 발견. 중복 제거 시작...")
    
    seen = set()
    deleted_count = 0
    
    for page in results:
        props = page['properties']
        name = props['Name']['title'][0]['plain_text'] if props['Name']['title'] else "No Name"
        date = props['Date']['date']['start'] if props['Date']['date'] else "No Date"
        
        # 키 생성: (이름, 날짜) 조합
        task_key = (name, date)
        
        if task_key in seen:
            # 이미 본 적 있는 (이름, 날짜) 조합이면 삭제
            requests.delete(f"https://api.notion.com/v1/blocks/{page['id']}", headers=HEADERS)
            print(f"🗑️ 중복 삭제됨: {name} ({date})")
            deleted_count += 1
        else:
            seen.add(task_key)
            
    print(f"✨ 작업 완료: 총 {deleted_count}개의 중복 항목을 제거했습니다.")

if __name__ == "__main__":
    clean_duplicates()
