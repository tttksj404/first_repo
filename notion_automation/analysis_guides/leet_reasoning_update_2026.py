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
# 추리논증 마스터북 페이지 ID
PAGE_ID = "314eacc8175a819d985bee4f4d006c90"

def update():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    
    # 최신 트렌드 보강 블록 정의
    blocks = [
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🔥 [Update] 2025-2026 추리논증 최신 경향 및 심화 전략"}}]}},
        {
            "type": "callout",
            "callout": {
                "rich_text": [{"text": {"content": "📢 핵심 변화: '논증 평가의 질적 고도화'. 단순 조력을 넘어 실험 설계의 논리적 허점을 파고드는 문항 급증."}}],
                "icon": {"emoji": "🧪"}, "color": "purple_background"
            }
        },
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "1. 논증 영역: 실험 및 가설 검증의 정교화"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "🔬 실험 설계 결함 찾기: 표본의 대표성뿐만 아니라 '대조군 설정의 오류', '교락 변인 통제 미흡'을 타격해야 함."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📊 통계적 유의성: 수치적 차이가 실제로 의미 있는 차이인지, 혹은 제3의 요인에 의한 우연인지 구분하는 선지 빈출."}}]}},
        
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "2. 규범 추론: 예외의 예외를 찾는 정밀함"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "⚖️ 단서 조항의 함정: 법조문 자체는 평이하나, 사례 적용 시 '다만, ~의 경우에는 제외한다'는 단서 조항을 3중으로 꼬아놓음."}}]}},
        
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "3. 추리/게임: 경우의 수 분류의 '단순화'"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"text": {"content": "과거: 복잡한 퀴즈 해결 능력 -> 현재: 여러 경우의 수 중 '모순이 발생하는 케이스'를 얼마나 빨리 소거하느냐의 속도전."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "🔢 수리 감각: 복잡한 계산 대신 '비율, 증감률, 기댓값'의 크기 비교를 통한 직관적 판단 요구."}}]}},
        
        {"type": "callout", "callout": {
            "rich_text": [{"text": {"content": "💡 ssafy 시점 혁신 오답노트: 단순히 틀린 이유를 적지 말고, '내가 왜 이 반례를 놓쳤는가?'에 대한 인지적 오류 과정을 코드로 짜듯 분석하세요."}}],
            "icon": {"emoji": "🧠"}, "color": "green_background"
        }}
    ]

    print("--- DEPLOYING REASONING UPDATES ---")
    res = requests.patch(url, headers=HEADERS, json={"children": blocks})
    if res.status_code == 200:
        print("SUCCESS: 2025/2026 Trends updated in Reasoning Masterbook.")
    else:
        print(f"FAILED: {res.text}")

if __name__ == "__main__":
    update()
