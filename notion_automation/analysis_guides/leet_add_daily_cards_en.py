import requests
import json
import time


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

def fill_daily_tasks_final(db_id):
    print(f"🚀 영어 속성명을 사용하여 카드 주입 시작: {db_id}")

    # 주입할 데일리 루틴 데이터 (체크 가능한 카드들)
    tasks = [
        {"Name": "[LEET] 🌅 08:30 Morning 예열 (언어 1지문)", "Tags": "언어이해", "SSAFY": "평일"},
        {"Name": "[SSAFY] 🏢 09:00 교육 및 알고리즘 집중", "Tags": "언어이해", "SSAFY": "평일"},
        {"Name": "[LEET] 🍴 13:10 Lunch 틈새 (추리 퀴즈)", "Tags": "추리논증", "SSAFY": "평일"},
        {"Name": "[LEET] 🔥 20:15 Night 집중 학습 (기출분석)", "Tags": "추리논증", "SSAFY": "평일"},
        {"Name": "[LEET] 💤 23:00 수면 및 회복 (7시간 사수)", "Tags": "언어이해", "SSAFY": "평일"}
    ]

    for task in tasks:
        payload = {
            "parent": {"database_id": db_id},
            "properties": {
                "Name": {"title": [{"text": {"content": task['Name']}}]},
                "Tags": {"multi_select": [{"name": task['Tags']}]},
                "SSAFY": {"select": {"name": task['SSAFY']}}
            }
        }
        resp = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json=payload)
        if resp.status_code == 200:
            print(f"✅ Success: {task['Name']}")
        else:
            print(f"❌ Failed: {resp.text}")
        time.sleep(0.3)

if __name__ == "__main__":
    ROUTINE_DB_ID = "314eacc8-175a-8100-b638-fdfe053da235"
    fill_daily_tasks_final(ROUTINE_DB_ID)
