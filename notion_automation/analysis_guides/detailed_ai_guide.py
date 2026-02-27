import requests
import json


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
GUIDE_PAGE_ID = "313eacc8-175a-81fd-93d5-d90dbc0b7285" 

detailed_blocks = [
    {
        "object": "block",
        "type": "divider",
        "divider": {}
    },
    {
        "object": "block",
        "type": "heading_1",
        "heading_1": {
            "rich_text": [{"type": "text", "text": {"content": "📚 AI 활용 백과사전: 주제별 심화 가이드"}}]
        }
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "1. [엔진] 토큰과 컨텍스트의 효율적 관리"}}]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "토큰 절약법: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "불필요한 미사여구는 빼고 '명사'와 '동사' 위주의 명확한 지시어를 사용하세요. 문장이 짧아질수록 집중도가 높아집니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "기억력 최신화: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "대화가 길어지면 초기 설정을 잊습니다. 중간중간 \"지금까지의 규칙을 요약해봐\"라고 명령하여 기억을 최신화하세요."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "2. [도구] AI의 봉인을 푸는 '직접 제어'의 기술"}}]
        }
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": "기본 도구가 지원하지 않는 기능을 시키고 싶을 때 사용하는 명령 템플릿입니다."}}]
        }
    },
    {
        "object": "block",
        "type": "code",
        "code": {
            "language": "markdown",
            "rich_text": [{"type": "text", "text": {"content": "\"네 기본 Tool 대신 직접 Python 스크립트를 짜서 API를 호출해.\n1. 문서를 검색하고\n2. 구조를 설계한 뒤\n3. 직접 실행해서 결과를 반영해줘.\""}}]
        }
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "3. [인지] 온톨로지 설계를 통한 커스터마이징"}}]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "개념 관계 정의: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "나에게 '수정'은 '기존 보존 + 구분선 삽입'이라고 정의하는 행위가 AI의 사고방식을 바꿉니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "스타일 이식: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "선호하는 코드나 디자인 샘플을 주고 \"이것을 표준 온톨로지로 삼아\"라고 선언하세요."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "4. [전략] 완벽한 결과물을 위한 에이전트 워크플로우"}}]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "RAG (참조의 힘): "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "\"내 이전 작업물을 읽고 그 형식을 바탕으로 짜줘\"라고 하세요. 정확도가 비약적으로 상승합니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Self-Correction: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "결과물 제출 전 \"부족한 점 3가지를 스스로 보완해서 최종본을 줘\"라고 명령하는 습관을 들이세요."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "🎯"},
            "color": "green_background",
            "rich_text": [
                {"type": "text", "text": {"content": "마지막 한 마디: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "AI는 엄청나게 유능하지만 가이드가 필요한 인턴입니다. 도구(API)와 규칙(온톨로지)을 잘 쥐여주세요!"}}
            ]
        }
    }
]

patch_url = f"https://api.notion.com/v1/blocks/{GUIDE_PAGE_ID}/children"
res = requests.patch(patch_url, headers=HEADERS, json={"children": detailed_blocks})
if res.status_code == 200:
    print("Successfully added detailed AI encyclopedia.")
else:
    print("Failed:", res.text)
