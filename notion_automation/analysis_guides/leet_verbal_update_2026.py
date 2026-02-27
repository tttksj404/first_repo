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
PAGE_ID = "314eacc8175a818a92dacd2d38cc4f4c"

def update():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    
    # Pre-formatted blocks to avoid encoding issues during script writing
    blocks = [
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🔥 [Update] 2025-2026 최신 기출 트렌드 분석"}}]}},
        {"type": "callout", "callout": {"rich_text": [{"text": {"content": "📢 키워드: '불친절한 평이함'. 지문은 짧아졌으나 정보 간의 미세한 관계 설정으로 변별력 확보."}}], "icon": {"emoji": "📉"}, "color": "orange_background"}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "1. 지문 소재의 변화: 융합과 실무"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "⚖️ 법학의 실종: 순수 법철학 대신 '법문학', '법사회학' 등 인문학적 융합 지문 대세."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "⚙️ 실무적 기술: '프로세스 마이닝', '알고리즘 데이터 처리' 등 현대적 소재 빈출."}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "2. 2026 필승 전략: '정교한 발췌'"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"text": {"content": "과거: 배경지식 중심 -> 현재: 선지 키워드와 지문 속 정보의 1:1 매칭 능력이 핵심."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "🔍 완곡한 표현 주의: 'A는 B일 수 있다' 속에 숨은 논리적 단절을 발굴할 것."}}]}},
        {"type": "callout", "callout": {"rich_text": [{"text": {"content": "💡 ssafy 시점 Tip: 알고리즘의 Edge Case를 찾듯, 선지의 예외 조건을 지문에서 발췌하세요."}}], "icon": {"emoji": "🎓"}, "color": "blue_background"}}
    ]

    print("--- DEPLOYING UPDATED TRENDS ---")
    res = requests.patch(url, headers=HEADERS, json={"children": blocks})
    if res.status_code == 200:
        print("SUCCESS: 2025/2026 Trends updated in Verbal Masterbook.")
    else:
        print(f"FAILED: {res.text}")

if __name__ == "__main__":
    update()
