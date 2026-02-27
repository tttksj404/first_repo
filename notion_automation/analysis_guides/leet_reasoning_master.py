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
PARENT_PAGE_ID = "231eacc8175a80b6b30be061e8f5a3c5"

def create_reasoning_page():
    url = "https://api.notion.com/v1/pages"
    
    content = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "Ⅰ. 논리 기초 (Formal Logic)"}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "1. 연역논리와 비연역논리"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "연역논리 (필연성 100%): 명제/술어논리. 형식적 타당성이 결론을 필연적 도출."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "비연역논리 (개연성): 귀납, 인과, 유비 추론. 전제가 결론의 개연성을 높임."}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "2. 명제논리 기호화 핵심 규칙"}}]}},
        {"type": "callout", "callout": {
            "rich_text": [{"type": "text", "text": {"content": "💡 조건문 변환: P -> Q == ~Q -> ~P == ~P or Q\n💡 수출입 법칙: P -> (Q -> R) == (P and Q) -> R"}}],
            "icon": {"emoji": "⚙️"}, "color": "blue_background"
        }},
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "Ⅱ. 비연역논리와 과학적 추론"}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "1. 인과관계와 밀(Mill)의 발견법"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "일치법(공통 요인), 차이법(유일 차이), 공변법(비례 변동)"}}]}},
        {"type": "callout", "callout": {
            "rich_text": [{"type": "text", "text": {"content": "⚠️ 교락 효과: 원인이 겹쳐 진정한 원인을 알 수 없는 상태. 변인 통제가 강화/약화의 핵심."}}],
            "icon": {"emoji": "🧪"}, "color": "yellow_background"
        }},
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "Ⅲ. 논증 분석 및 비판 (강화/약화)"}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "1. 강화/약화 매커니즘"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "강화: 전제-주장 연관성 증명, 전제 참 보강, 대안 가설 배제"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "약화: 연관성 부정, 대안적 원인 제시, 표본 편향성 지적"}}]}},
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "Ⅳ. 영역별 특화 전략"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "🏢 법학 추리: [주-방-장-행-시-객] 쪼개기. 요건/효과 구분."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "🧩 논리 게임: 그룹핑(6인 이상) 및 사냥개 작전(확정값부터 채우기)."}}]}}
    ]

    data = {
        "parent": {"page_id": PARENT_PAGE_ID},
        "icon": {"emoji": "📘"},
        "cover": {"type": "external", "external": {"url": "https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?auto=format&fit=crop&w=1350&q=80"}},
        "properties": {"title": {"title": [{"text": {"content": "📘 [완전판] LEET 추리논증 기본 정리 및 전략 마스터북"}}]}},
        "children": content
    }
    
    print("--- DEPLOYING REASONING MASTERBOOK ---")
    res = requests.post(url, headers=HEADERS, json=data)
    if res.status_code == 200:
        print(f"SUCCESS: {res.json()['url']}")
    else:
        print(f"FAILED: {res.text}")

if __name__ == "__main__":
    create_reasoning_page()
