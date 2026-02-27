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

def create_database(parent_page_id, title, properties):
    """Database Creation Helper"""
    url = "https://api.notion.com/v1/databases"
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties
    }
    res = requests.post(url, headers=HEADERS, json=payload)
    if res.status_code == 200:
        return res.json()['id']
    else:
        print(f"FAILED to create database '{title}': {res.text}")
        return None

def append_blocks_safely(block_id, blocks):
    """Chunked Patch Logic with Error Handling"""
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        res = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if res.status_code != 200:
            print(f"ERROR appending blocks: {res.text}")
        time.sleep(1)

def build_workspace(parent_id):
    # STEP 1: Main Page
    print("--- STEP 1: Creating Main Page ---")
    page_data = {
        "parent": {"page_id": parent_id},
        "icon": {"emoji": "🎓"},
        "cover": {"type": "external", "external": {"url": "https://images.unsplash.com/photo-1505664194779-8beaceb93744?auto=format&fit=crop&w=1350&q=80"}},
        "properties": {"title": {"title": [{"text": {"content": "🏆 [2026] LEET 140+ 합격 사수: SSAFY 병행 마스터 워크스페이스"}}]}}
    }
    res = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json=page_data)
    main_page_id = res.json()['id']
    print(f"Main page created: {main_page_id}")

    # STEP 2: Section 1 (Roadmap)
    print("--- STEP 2: Deploying Roadmap ---")
    roadmap_blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "📍 [섹션 1] LEET 3월~7월 마스터 로드맵"}}]}},
        {
            "type": "callout",
            "callout": {
                "rich_text": [{"text": {"content": "• 3월: 기출 해부 (2017~2025 전 문항 분석)\n• 4월: 약점 정복 (과학/철학 소재 & PSAT 병행)\n• 5월: 체급 증강 (입법고시 기출 등 극악 난이도)\n• 6월: 실전 시뮬 (매주 토요일 모의고사)\n• 7월: 파이널 (오답 노트 & 행동 강령 무한 반복)"}}],
                "icon": {"emoji": "📅"}, "color": "blue_background"
            }
        },
        {"type": "divider", "divider": {}}
    ]
    append_blocks_safely(main_page_id, roadmap_blocks)

    # STEP 3: Section 2 (Routine DB)
    print("--- STEP 3: Creating Routine DB ---")
    routine_props = {
        "이름": {"title": {}},
        "날짜": {"date": {}},
        "태그": {"multi_select": {"options": [{"name": "언어이해", "color": "red"}, {"name": "추리논증", "color": "yellow"}]}},
        "SSAFY 연동": {"select": {"options": [{"name": "평일", "color": "orange"}, {"name": "주말", "color": "blue"}]}}
    }
    create_database(main_page_id, "⏰ [섹션 2] 데일리 루틴 & 체크리스트", routine_props)

    # STEP 4: Section 3 (Feedback DB)
    print("--- STEP 4: Creating Feedback DB ---")
    feedback_props = {
        "출처": {"title": {}},
        "유형": {"select": {"options": [{"name": "법률형", "color": "blue"}, {"name": "논리게임", "color": "green"}]}},
        "내 오답 논리": {"rich_text": {}},
        "출제자 논리": {"rich_text": {}},
        "행동 강령": {"rich_text": {}}
    }
    create_database(main_page_id, "🔍 [섹션 3] 논리 피드백 연구소", feedback_props)

    print("\nSUCCESS: All sections deployed.")
    print(f"URL: https://www.notion.so/{main_page_id.replace('-', '')}")

if __name__ == "__main__":
    PARENT_ID = "231eacc8175a80b6b30be061e8f5a3c5"
    build_workspace(PARENT_ID)
