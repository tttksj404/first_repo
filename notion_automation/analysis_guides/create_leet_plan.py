import requests
import json

# 1. API 설정 (sync_notion_key.py에 의해 관리됨)

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

def create_leet_optimized_page(parent_page_id):
    url = "https://api.notion.com/v1/pages"
    
    payload = {
        "parent": {"page_id": parent_page_id},
        "icon": {"emoji": "🔥"},
        "cover": {
            "type": "external",
            "external": {"url": "https://images.unsplash.com/photo-1434030216411-0b793f4b4173?ixlib=rb-1.2.1&auto=format&fit=crop&w=1350&q=80"}
        },
        "properties": {
            "title": {
                "title": [{"text": {"content": "[2026] LEET 140+ 정복 데일리 마스터 플랜 (SSAFY 병행)"}}]
            }
        },
        "children": [
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"text": {"content": "💡 이 페이지는 SSAFY 교육과 LEET 학습의 완벽한 밸런스를 위해 설계되었습니다.\n체크박스를 클릭하여 완료 여부를 표시하고, 하단에 오답 논리를 기록하세요."}}],
                    "icon": {"emoji": "📌"},
                    "color": "yellow_background"
                }
            },
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "⏰ Daily Routine & Checklist"}}]}},
            
            # 08:30 - 09:00
            {"object": "block", "type": "to_do", "to_do": {"rich_text": [{"text": {"content": "08:30 - 09:00 | Morning 예열: 잠든 뇌를 깨우는 언어이해 지문 1개 풀이 (리듬 집중)"}}], "checked": False}},
            
            # 09:00 - 18:00
            {"object": "block", "type": "to_do", "to_do": {"rich_text": [{"text": {"content": "09:00 - 18:00 | SSAFY 교육: 알고리즘 로직을 추리논증과 연결하여 생각하기"}}], "checked": False}},
            
            # 13:10 - 13:45
            {"object": "block", "type": "to_do", "to_do": {"rich_text": [{"text": {"content": "13:10 - 13:45 | Lunch 틈새: 추리논증 논리 퀴즈 3~5개 또는 전날 틀린 지문 재독해"}}], "checked": False}},
            
            # 20:15 - 23:00 (화,수,목)
            {"object": "block", "type": "to_do", "to_do": {"rich_text": [{"text": {"content": "20:15 - 23:00 | Night 집중 학습(화,수,목): 언어 2지문 + 추리 15문제 + 심층 리뷰"}}], "checked": False}},
            
            # 20:40 - 23:00 (월,금)
            {"object": "block", "type": "to_do", "to_do": {"rich_text": [{"text": {"content": "20:40 - 23:00 | Night 복습(월,금): 스터디 내용 정리 및 취약 파트 보충 학습"}}], "checked": False}},
            
            # 23:00 - 07:00
            {"object": "block", "type": "to_do", "to_do": {"rich_text": [{"text": {"content": "23:00 - 07:00 | 수면 및 회복: 뇌 정보 정리를 위한 7시간 이상의 숙면 사수"}}], "checked": False, "color": "blue"}},
            
            {"object": "block", "type": "divider", "divider": {}},
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "✍️ 오늘의 논리 피드백 (기록 공간)"}}]}},
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"text": {"content": "매일 밤, 가장 고민했던 지문이나 틀린 문제의 '나의 오답 논리'를 아래에 작성하세요.\n작성 후 제가 분석하여 '접근 방식'을 덧붙여 드립니다."}}],
                    "icon": {"emoji": "📝"},
                    "color": "gray_background"
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": "[기출분석 기록 예시]\n- 문제: 2024 언어이해 15번\n- 나의 오답 논리: 본문의 'A이면 B이다'를 'B이면 A이다'로 역으로 해석함.\n- 정답의 필연성: 2문단 4행의 조건절 확인 필수.", "annotations": {"italic": True}}], "color": "gray"}}
            }
        ]
    }

    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        print(f"✅ LEET 최적화 페이지 생성 성공: {response.json().get('url')}")
    else:
        print(f"❌ 실패: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    # 사용자님의 노션 페이지 ID 입력 (실제 사용 시 변경)
    PARENT_ID = "6159c3d2e2734a1796be57f208191983" 
    create_leet_optimized_page(PARENT_ID)
