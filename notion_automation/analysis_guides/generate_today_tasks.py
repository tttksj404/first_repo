import requests
import json
import time
from datetime import datetime


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

def generate_today_routine(db_id):
    today_str = datetime.now().strftime("%Y-%m-%d")
    print(f"📅 {today_str} LEET 루틴 생성 시작...")

    tasks = [
        {"Name": "🌅 [LEET] 아침 예열 (언어 1지문)", "Tags": "언어이해", "SSAFY": "평일"},
        {"Name": "🏢 [SSAFY] 교육 및 알고리즘 집중", "Tags": "공통", "SSAFY": "평일"},
        {"Name": "🍴 [LEET] 점심 틈새 (추리 퀴즈)", "Tags": "추리논증", "SSAFY": "평일"},
        {"Name": "🔥 [LEET] 저녁 집중 학습 (기출분석)", "Tags": "공통", "SSAFY": "평일"},
        {"Name": "💤 [LEET] 23:00 수면 사수 (숙면 회복)", "Tags": "공통", "SSAFY": "평일"}
    ]

    for task in tasks:
        payload = {
            "parent": {"database_id": db_id},
            "properties": {
                "Name": {"title": [{"text": {"content": task['Name']}}]},
                "Tags": {"multi_select": [{"name": task['Tags']}]},
                "SSAFY": {"select": {"name": task['SSAFY']}},
                "Date": {"date": {"start": today_str}}, # 오늘 날짜 주입
                "Done": {"checkbox": False} # 미완료 상태로 시작
            }
        }
        res = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json=payload)
        if res.status_code == 200:
            print(f"✅ 생성 완료: {task['Name']}")
        else:
            print(f"❌ 실패: {res.text}")
        time.sleep(0.3)

if __name__ == "__main__":
    ROUTINE_DB_ID = "314eacc8-175a-8100-b638-fdfe053da235"
    generate_today_routine(ROUTINE_DB_ID)
