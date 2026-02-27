import requests
import json

# 1. API 설정 (중앙 관리되는 키 사용)

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

def create_exclusive_leet_page(parent_id):
    url = "https://api.notion.com/v1/pages"
    
    # 📝 페이지 구성 데이터
    payload = {
        "parent": {"page_id": parent_id},
        "icon": {"emoji": "🎓"},
        "cover": {
            "type": "external",
            "external": {"url": "https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?ixlib=rb-1.2.1&auto=format&fit=crop&w=1350&q=80"}
        },
        "properties": {
            "title": {
                "title": [{"text": {"content": "🏆 [2026] LEET 140+ 합격 사수: SSAFY 병행 대시보드"}}]
            }
        },
        "children": [
            # 📌 핵심 목표 및 마인드셋
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"text": {"content": "💡 전략: SSAFY 교육 중엔 '논리적 사고'를 훈련하고, 저녁엔 '기출의 필연성'을 분석한다.
🚫 원칙: 23:00 취침 엄수. 수면 부족은 추론 능력의 적이다."}}],
                    "icon": {"emoji": "🚨"},
                    "color": "red_background"
                }
            },
            
            # ⏰ 데일리 루틴 (체크리스트)
            {"object": "block", "type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "⏰ 데일리 루틴 (수행 체크)"}}]}},
            {"object": "block", "type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🌅 08:30 - 09:00 | Morning 예열: 언어이해 1지문 (점수보다 리듬)"}}], "checked": False}},
            {"object": "block", "type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🏢 09:00 - 18:00 | SSAFY 교육: 알고리즘 로직 = 추리논증 연계 사고"}}], "checked": False}},
            {"object": "block", "type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🍴 13:10 - 13:45 | Lunch 틈새: 추리 퀴즈 3~5개 or 오답 재독해"}}], "checked": False}},
            {"object": "block", "type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🔥 20:15 - 23:00 | Night 집중(화,수,목): 기출 분석 메인 (언어2+추리15)"}}], "checked": False}},
            {"object": "block", "type": "to_do", "to_do": {"rich_text": [{"text": {"content": "📚 20:40 - 23:00 | Night 복습(월,금): 스터디 정리 및 취약 파트 보충"}}], "checked": False}},
            {"object": "block", "type": "to_do", "to_do": {"rich_text": [{"text": {"content": "💤 23:00 - 07:00 | 수면 및 회복: 7시간 이상 숙면 (기억 저장소 가동)"}}], "checked": False, "color": "blue"}},
            
            {"object": "block", "type": "divider", "divider": {}},

            # 🔍 기출 분석 및 논리 피드백 공간
            {"object": "block", "type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🔍 오늘의 기출 분석 & 논리 피드백"}}]}},
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"text": {"content": "아래에 [문제번호 / 나의 오답 논리 / 정답의 근거]를 작성하세요.
작성 완료 후 저에게 분석을 요청하면, 'AI 접근 가이드'를 덧붙여 드립니다."}}],
                    "icon": {"emoji": "✍️"},
                    "color": "gray_background"
                }
            },
            {
                "object": "block",
                "type": "quote",
                "quote": {"rich_text": [{"text": {"content": "작성 예시:
- 2024 언어 7번: 지문의 '단서' 조건을 간과하여 범위를 너무 넓게 잡음.
- 교정: 다음부턴 '오직', '한하여' 같은 한정 표현에 반드시 세모 표시할 것."}}]}
            },
            
            # 실제 기록이 시작될 공간
            {"object": "block", "type": "divider", "divider": {}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "📅 (여기에 오늘의 날짜와 분석 내용을 입력하세요...)", "annotations": {"italic": True}}}]}}
        ]
    }

    print("🚀 노션 페이지 생성 중...")
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        result = response.json()
        print(f"✨ 생성 완료! 아래 링크에서 확인하세요:")
        print(f"🔗 {result.get('url')}")
    else:
        print(f"❌ 실패 ({response.status_code}): {response.text}")

if __name__ == "__main__":
    # 이 페이지를 생성할 부모 페이지 ID
    PARENT_PAGE_ID = "6159c3d2e2734a1796be57f208191983" 
    create_exclusive_leet_page(PARENT_PAGE_ID)
