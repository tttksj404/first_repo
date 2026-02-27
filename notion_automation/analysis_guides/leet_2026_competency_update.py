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

def update_2026_competency():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    
    # 2026 기출 분석 기반 필수 역량 데이터
    content = [
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🧐 2026 기출 분석: 당신이 반드시 갖춰야 할 3대 심화 역량"}}]}},
        {
            "type": "callout",
            "callout": {
                "rich_text": [{"text": {"content": "📢 2026년의 경고: 이제 지문은 '읽는 것'이 아니라 '설계도를 복원하는 것'이다. 텍스트 너머의 구조를 보지 못하면 오선지에 낚인다."}}],
                "icon": {"emoji": "⚠️"}, "color": "yellow_background"
            }
        },
        
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "역량 1. 모델링 및 도표 해독 능력 (Modeling Fluency)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 대상 지문: 4~6번(DMN/BPMN), 7~9번(정치 모델/그래프), 25~27번(깁스 에너지/미분 기울기)."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 핵심 기술: 글자 정보를 'IF-THEN' 조건문이나 '변수 간 상관관계'로 즉시 변환해야 함. 특히 깁스-뒤엠 식처럼 수식의 '반비례/방향성'을 선지에 적용하는 속도가 생명."}}]}},

        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "역량 2. 미세 개념어의 '원자적 분리' (Micro-Distinction)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 대상 지문: 13~15번(인식적 수의주의), 22~24번(사토리오의 심적 무위)."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 핵심 기술: '하지 않기로 결심한 것(행위)'과 '하겠다고 결심하지 않은 것(무위)'의 차이를 구분하는 능력. 2026 리트는 이 미세한 틈을 타격하여 오답을 만듦."}}]}},

        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "역량 3. 다층적 인과 추론 및 도구변수 이해 (Causal Inference)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 대상 지문: 16~18번(아제모을루의 제도와 성장)."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 핵심 기술: 단순 상관관계(Correlation)와 진정한 인과관계(Causality)를 구분하고, 제3의 요인을 제거하기 위한 '도구변수(Z)'의 메커니즘을 텍스트로만 읽고 이해해야 함."}}]}},

        {"type": "callout", "callout": {
            "rich_text": [{"text": {"content": "🎓 SSAFY 연계 전략: 4~6번 DMN 지문은 알고리즘의 의사결정 트리와 100% 일치합니다. 코딩할 때 조건문을 짜는 것처럼 지문을 '구조화'하세요. 이것이 140점의 비결입니다."}}],
            "icon": {"emoji": "💻"}, "color": "blue_background"
        }}
    ]

    print("--- DEPLOYING 2026 COMPETENCY UPDATES ---")
    res = requests.patch(url, headers=HEADERS, json={"children": content})
    if res.status_code == 200:
        print("SUCCESS: 2026 Competencies added to Verbal Masterbook.")
    else:
        print(f"FAILED: {res.text}")

if __name__ == "__main__":
    update_2026_competency()
