import requests
import json
import time

# 1. API Configuration

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

def fill_daily_tasks(main_page_id):
    # 1. 메인 페이지의 하위 블록 확인하여 DB ID 추출
    url = f"https://api.notion.com/v1/blocks/{main_page_id}/children"
    res = requests.get(url, headers=HEADERS)
    db_ids = [b['id'] for b in res.json().get('results', []) if b['type'] == 'child_database']
    
    if not db_ids:
        print("❌ Error: 데이터베이스를 찾을 수 없습니다.")
        return

    # 첫 번째 DB가 데일리 루틴 DB입니다.
    routine_db_id = db_ids[0]
    print(f"✅ 데일리 루틴 DB 발견: {routine_db_id}")

    # 2. 주입할 데일리 루틴 데이터 (체크 가능한 카드들)
    tasks = [
        {"이름": "[LEET] 🌅 08:30 Morning 예열 (언어 1지문)", "태그": "언어이해", "SSAFY": "평일"},
        {"이름": "[SSAFY] 🏢 09:00 교육 및 알고리즘 집중", "태그": "언어이해", "SSAFY": "평일"}, # 예비 태그 사용
        {"이름": "[LEET] 🍴 13:10 Lunch 틈새 (추리 퀴즈)", "태그": "추리논증", "SSAFY": "평일"},
        {"이름": "[LEET] 🔥 20:15 Night 집중 학습 (기출분석)", "태그": "추리논증", "SSAFY": "평일"},
        {"이름": "[LEET] 💤 23:00 수면 및 회복 (7시간 사수)", "태그": "언어이해", "SSAFY": "평일"}
    ]

    for task in tasks:
        payload = {
            "parent": {"database_id": routine_db_id},
            "properties": {
                "이름": {"title": [{"text": {"content": task['이름']}}]},
                "태그": {"multi_select": [{"name": task['태그']}]},
                "SSAFY 연동": {"select": {"name": task['SSAFY']}},
                "상태": {"status": {"name": "시작 전"}}
            }
        }
        resp = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json=payload)
        if resp.status_code == 200:
            print(f"✅ Success: {task['이름']}")
        else:
            print(f"❌ Failed: {resp.text}")
        time.sleep(0.3)

if __name__ == "__main__":
    # 메인 대시보드 ID
    MAIN_PAGE_ID = "314eacc8-175a-817c-8fa6-c89fd1e36a66"
    fill_daily_tasks(MAIN_PAGE_ID)
