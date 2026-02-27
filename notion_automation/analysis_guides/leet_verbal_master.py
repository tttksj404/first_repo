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
# 🛠️ 확실히 접근 가능한 '스터디 로드맵' 페이지 ID로 변경
PARENT_PAGE_ID = "231eacc8175a80b6b30be061e8f5a3c5"

def create_verbal_page():
    url = "https://api.notion.com/v1/pages"
    
    content = [
        {"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": "🎯 목표: 2025/2026 기출 분석을 통한 오답 필터 정교화\n💡 원칙: 출제자 로직 역추적 및 선지 판단 시간 단축"}}], "icon": {"emoji": "🛡️"}, "color": "red_background"}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "Ⅰ. 출제자의 '거름망' 알고리즘"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "🔗 인과 비약: A→B→C 과정에서 B 생략 또는 A-C 오연결"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "⚖️ 양상 오류: 지문(개연성) vs 선지(단정/필연). 반례 체크 필수"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "📉 관계 역전: 비례/반비례 관계를 선지에서 반대로 서술"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "📦 범주 혼동: 상/하위 개념 혼동 및 공통/차이점 바꿔치기"}}]}},
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "Ⅱ. 독해 및 접근 마인드셋"}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "1. 발문 및 문단 활용"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "발문 선스캔(유형 파악) → 첫 문단 쟁점 파악 → 문단별 병행 풀이"}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "2. 이항 대립 구조"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "학자/이론 대립 시 [공통점/차이점] 기호화 메모 필수"}}]}},
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "Ⅲ. 세부 킬러 논리 기술"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "🔄 패러프레이징: 단어가 달라도 문맥적 취지가 같으면 참"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "🔚 마지막 문단: '그러나/결국' 이후의 필자 견해가 정답 근거"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "⚠️ 조건부 서술: '다만, ~한 경우' 등 단서 조항 선지 반영 체크"}}]}},
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "🧪 [확장] 2025/2026 실전 기출 분석"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "3월부터의 분석 내용을 이곳에 누적합니다."}, "annotations": {"italic": True}}]}}
    ]

    data = {
        "parent": {"page_id": PARENT_PAGE_ID},
        "icon": {"emoji": "📕"},
        "cover": {"type": "external", "external": {"url": "https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?auto=format&fit=crop&w=1350&q=80"}},
        "properties": {"title": {"title": [{"text": {"content": "📕 [완전판] LEET 언어이해 기출 출제원리 및 오답 거름망"}}]}},
        "children": content
    }
    
    print("--- DEPLOYING VERBAL MASTERBOOK ---")
    res = requests.post(url, headers=HEADERS, json=data)
    if res.status_code == 200:
        print(f"SUCCESS: {res.json()['url']}")
    else:
        print(f"FAILED: {res.text}")

if __name__ == "__main__":
    create_verbal_page()
