import requests
import json
import time
from datetime import datetime

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
DB_ID = "314eacc8-175a-8100-b638-fdfe053da235"
START_DATE = datetime(2026, 3, 2) # 3월 2일 정식 시작

def get_today_existing_tasks(today_str):
    """오늘 날짜로 이미 생성된 할 일 목록을 가져와서 중복을 방지합니다."""
    url = f"https://api.notion.com/v1/databases/{DB_ID}/query"
    query_data = {
        "filter": {
            "property": "Date",
            "date": {"equals": today_str}
        }
    }
    res = requests.post(url, headers=HEADERS, json=query_data)
    if res.status_code == 200:
        return [page['properties']['Name']['title'][0]['plain_text'] 
                for page in res.json().get('results', []) 
                if page['properties']['Name']['title']]
    return []

def generate_routine():
    now = datetime.now()
    
    # ⚠️ 3월 2일 전이면 작동하지 않음 (단, 오늘 테스트를 위해 주석 처리하거나 날짜 확인)
    if now < START_DATE:
        print(f"⏳ 아직 정식 시작일({START_DATE.strftime('%Y-%m-%d')}) 전입니다. 대기 중...")
        return

    today_str = now.strftime("%Y-%m-%d")
    weekday = now.weekday() # 0:월, 4:금
    
    # 1. 오늘 이미 생성된 작업 확인
    existing_tasks = get_today_existing_tasks(today_str)
    print(f"🕵️ 오늘({today_str}) 이미 존재하는 작업: {len(existing_tasks)}개")

    # 2. 요일별 목표 루틴 정의
    base_tasks = [
        {"Name": "🌅 [LEET] 08:30 Morning 예열 (언어 1지문)", "Tags": "언어이해", "SSAFY": "평일"},
        {"Name": "🏢 [SSAFY] 09:00 교육 및 알고리즘 집중", "Tags": "언어이해", "SSAFY": "평일"},
        {"Name": "🍴 [LEET] 13:10 Lunch 틈새 (추리 퀴즈)", "Tags": "추리논증", "SSAFY": "평일"}
    ]

    # 화/수/목: 기출 메인, 월/금: 스터디 복습
    if weekday in [1, 2, 3]:
        base_tasks.append({"Name": "🔥 [LEET] 20:15 Night 집중 학습 (기출 분석 메인)", "Tags": "추리논증", "SSAFY": "평일"})
    elif weekday in [0, 4]:
        base_tasks.append({"Name": "📚 [LEET] 20:40 Night 복습 (스터디 내용 정리)", "Tags": "추리논증", "SSAFY": "월금(스터디)"})
    
    base_tasks.append({"Name": "💤 [LEET] 23:00 수면 사수 (숙면 회복)", "Tags": "언어이해", "SSAFY": "평일"})

    # 3. 중복되지 않은 항목만 생성
    for task in base_tasks:
        if task['Name'] in existing_tasks:
            print(f"⏩ 건너뜀 (중복): {task['Name']}")
            continue
            
        payload = {
            "parent": {"database_id": DB_ID},
            "properties": {
                "Name": {"title": [{"text": {"content": task['Name']}}]},
                "Tags": {"multi_select": [{"name": task['Tags']}]},
                "SSAFY": {"select": {"name": task['SSAFY']}},
                "Date": {"date": {"start": today_str}},
                "Done": {"checkbox": False}
            }
        }
        res = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json=payload)
        if res.status_code == 200:
            print(f"✅ 생성 완료: {task['Name']}")
        time.sleep(0.3)

if __name__ == "__main__":
    generate_routine()
