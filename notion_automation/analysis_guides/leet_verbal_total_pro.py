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
    
    # 2025-2026 통합 역량 분석 데이터
    blocks = [
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "💎 2025-2026 통합 분석: 고득점(140+)을 위한 3대 절대 역량"}}]}},
        {
            "type": "callout",
            "callout": {
                "rich_text": [{"text": {"content": "📢 총평: 리트는 '지식'을 묻지 않는다. 생소한 '시스템 설계도'를 던져주고, 그 안에서 데이터가 어떻게 흐르는지(Flow) 1초 만에 파악하길 원한다."}}],
                "icon": {"emoji": "🏗️"}, "color": "blue_background"
            }
        },
        
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "역량 1. 시스템 렌더링 능력 (Structural Rendering)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 근거: 25년 헴 합성(화학), 트랜잭션(CS) / 26년 DMN(모델링), 깁스 에너지(물리)."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 기술: 텍스트로 된 '다단계 효소 촉매 과정'이나 '격리성 수준'을 읽자마자 머릿속에 '순서도(Flowchart)'를 그리는 능력입니다."}}]}},

        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "역량 2. 원자적 뉘앙스 분리력 (Atomic Nuance Distinction)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 근거: 25년 규칙 유지 vs 규칙 준수(라이언스) / 26년 결심하지 않음 vs 하지 않기로 결심함(사토리오)."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 기술: 일상어로는 비슷해 보이지만 논리적으로는 'A와 Not A' 수준으로 다른 개념을 끝까지 물고 늘어지는 집요함입니다."}}]}},

        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "역량 3. 동태적 변수 추적력 (Dynamic Variable Tracking)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 근거: 25년 솔로우 모형(저축률-자본량-소비의 상관관계) / 26년 도구변수(Z-X-Y 인과 경로)."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 기술: 한 변수가 변할 때 다른 변수들이 연쇄적으로 어떻게 변하는지(X↑ -> Y↓ -> Z↑)를 실시간으로 시뮬레이션하는 역량입니다."}}]}},

        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🏋️ 평소 실전 연습 방법 (Daily Training)"}}]}},
        
        {"type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "1. '화이트보드 매핑' (Mapping)"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "지문을 읽은 후, 책을 덮고 A4 용지에 해당 지문의 '인과 관계도'나 '시스템 구조'를 30초 안에 그려보세요. 그림이 안 그려진다면 정보 간 관계를 놓친 것입니다."}}]}},

        {"type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "2. '선지 원자 폭격' (Fact-Check)"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "정답을 맞혔더라도 모든 오답 선지의 '단 한 단어' 때문에 틀린 이유를 지문에서 찾으세요. (예: '반드시' 때문인지, '주체' 때문인지)."}}]}},

        {"type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "3. 'SSAFY 알고리즘 연계' (Algorithmic Thinking)"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "알고리즘 문제를 풀 때 조건문(if)과 반복문(while)의 경계 조건을 따지는 습관을 언어이해 지문의 '단서 조항(~에 한하여, 다만)'에 그대로 적용하세요."}}]}},

        {"type": "callout", "callout": {
            "rich_text": [{"text": {"content": "🎓 결론: 2025-2026 리트는 당신이 '똑똑한 기계'처럼 텍스트를 처리하길 원합니다. 배경지식에 매몰되지 말고, 철저하게 '관계'와 '구조'만 파고드세요."}}],
            "icon": {"emoji": "🚀"}, "color": "red_background"
        }}
    ]

    print("--- DEPLOYING TOTAL COMPETENCY UPDATES ---")
    res = requests.patch(url, headers=HEADERS, json={"children": blocks})
    if res.status_code == 200:
        print("SUCCESS: 2025-2026 Integrated Strategy added to Notion.")
    else:
        print(f"FAILED: {res.text}")

if __name__ == "__main__":
    update()
