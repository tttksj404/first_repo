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

def rename_properties(db_id):
    url = f"https://api.notion.com/v1/databases/{db_id}"
    
    # 🔍 기존 속성 ID를 기반으로 이름을 영어로 강제 변경
    payload = {
        "properties": {
            "title": {"name": "Name"}, # '이름' -> 'Name'
            "tGSe": {"name": "Date"}, # '날짜' -> 'Date'
            "Yo%7B%3B": {"name": "Tags"}, # '태그' -> 'Tags'
            "_%3CjQ": {"name": "SSAFY"} # 'SSAFY 연동' -> 'SSAFY'
        }
    }
    
    res = requests.patch(url, headers=HEADERS, json=payload)
    if res.status_code == 200:
        print("✅ DB 속성명이 영어로 안전하게 변경되었습니다.")
    else:
        print(f"❌ 실패: {res.text}")

if __name__ == "__main__":
    ROUTINE_DB_ID = "314eacc8-175a-8100-b638-fdfe053da235"
    rename_properties(ROUTINE_DB_ID)
