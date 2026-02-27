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

def get_db_ids(page_id):
    """메인 페이지에서 생성된 DB들의 ID를 가져옵니다."""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    res = requests.get(url, headers=HEADERS)
    db_ids = []
    for block in res.json().get('results', []):
        if block['type'] == 'child_database':
            db_ids.append(block['id'])
    return db_ids

def create_page_in_db(db_id, properties):
    """DB에 새로운 행(페이지)을 생성합니다."""
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": db_id},
        "properties": properties
    }
    requests.post(url, headers=HEADERS, json=payload)

def fill_templates(main_page_id):
    db_ids = get_db_ids(main_page_id)
    if len(db_ids) < 2:
        print("Error: Could not find both databases.")
        return

    # DB 순서가 생성 순서대로라면: index 0 = 루틴, index 1 = 피드백
    routine_db_id = db_ids[0]
    feedback_db_id = db_ids[1]

    print("--- Filling Section 2: Daily Routine Examples ---")
    routine_examples = [
        {
            "이름": {"title": [{"text": {"content": "[LEET] 아침 예열"}}]},
            "태그": {"multi_select": [{"name": "언어이해"}]},
            "SSAFY 연동": {"select": {"name": "평일"}},
            "상태": {"status": {"name": "시작 전"}}
        },
        {
            "이름": {"title": [{"text": {"content": "[SSAFY] 교육 및 알고리즘"}}]},
            "태그": {"multi_select": [{"name": "공통"}]},
            "SSAFY 연동": {"select": {"name": "평일"}},
            "상태": {"status": {"name": "진행 중"}}
        },
        {
            "이름": {"title": [{"text": {"content": "[LEET] 저녁 집중 학습"}}]},
            "태그": {"multi_select": [{"name": "추리논증"}]},
            "SSAFY 연동": {"select": {"name": "평일"}},
            "상태": {"status": {"name": "시작 전"}}
        }
    ]
    for ex in routine_examples:
        create_page_in_db(routine_db_id, ex)

    print("--- Filling Section 3: Logic Feedback Examples ---")
    feedback_examples = [
        {
            "출처": {"title": [{"text": {"content": "2025학년도 추리 15번"}}]},
            "유형": {"select": {"name": "논리게임"}},
            "내 오답 논리": {"rich_text": [{"text": {"content": "A가 참이면 B도 참이라고 생각해서 3번을 골랐음."}}]},
            "출제자 논리": {"rich_text": [{"text": {"content": "지문 5행에서 '반드시'가 아닌 '일반적으로'라고 명시했으므로 B는 거짓일 수 있음."}}]},
            "행동 강령": {"rich_text": [{"text": {"content": "양상 부사(반드시, 대개, 흔히)에 세모 표시하고 역명제 주의하기."}}]}
        }
    ]
    for ex in feedback_examples:
        create_page_in_db(feedback_db_id, ex)

    print("SUCCESS: Templates and examples added.")

if __name__ == "__main__":
    MAIN_PAGE_ID = "314eacc8-175a-817c-8fa6-c89fd1e36a66"
    fill_templates(MAIN_PAGE_ID)
