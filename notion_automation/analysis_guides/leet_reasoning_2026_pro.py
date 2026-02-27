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
    
    # 2026 기출 분석 기반 데이터
    blocks = [
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🧐 2026 추리논증 심층 해부: 140점 돌파를 위한 필수 역량"}}]}},
        {
            "type": "callout",
            "callout": {
                "rich_text": [{"text": {"content": "📢 2026년의 특징: 지식은 도구일 뿐, '추상적 모델'을 '구체적 상황'에 매핑하는 속도가 승부처. 특히 공학/경제 모델 지문이 킬러로 등장함."}}],
                "icon": {"emoji": "🛰️"}, "color": "purple_background"
            }
        },
        
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "역량 1. 모델 시뮬레이션 능력 (Machine Logic Simulation)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 대상 문항: 31번(튜링기계 상태 전이), 36번(홉필드 신경망 에너지 최소화)."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 핵심 기술: 글자로 된 '기계표'나 '물리 모델'을 읽고, 머릿속에서 단계를 밟아 결과를 예측하는 능력. 코딩의 'Trace' 과정과 흡사함."}}]}},

        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "역량 2. 통계 및 수리적 '차이' 분석력 (Quantitative Difference)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 대상 문항: 27번(이중차분법 수식), 22번(증거의 기울기 vs 무게)."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 핵심 기술: (x-z) - (y-w)와 같은 수식의 의미를 '도시 간 차이 제거'라는 논리적 맥락으로 치환하는 능력. 숫자가 아닌 '논리적 구조'로 계산을 바라봐야 함."}}]}},

        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "역량 3. 규범/윤리 논쟁의 '원칙 충돌' 해결 (Ethical Dialectics)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 대상 문항: 13번(A인종 편향과 정의), 15번(후회의 합리성)."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 핵심 기술: '일부의 정의' vs '전체의 부정의'와 같은 가치관의 대립 구도를 명확히 파악하고, 각 입장이 공격받는 지점(반례)을 선지에서 찾는 능력."}}]}},

        {"type": "callout", "callout": {
            "rich_text": [{"text": {"content": "🎓 SSAFY 연계 꿀팁: 31번 튜링기계나 36번 신경망은 SSAFY에서 배우는 알고리즘과 인공지능 기초 지식입니다. 전공 지식을 '추리 도구'로 적극 활용하여 시간 세이브를 극대화하세요."}}],
            "icon": {"emoji": "💡"}, "color": "blue_background"
        }}
    ]

    print("--- DEPLOYING 2026 REASONING ANALYSIS ---")
    res = requests.patch(url, headers=HEADERS, json={"children": blocks})
    if res.status_code == 200:
        print("SUCCESS: 2026 Reasoning Analysis added to Notion.")
    else:
        print(f"FAILED: {res.text}")

if __name__ == "__main__":
    update()
