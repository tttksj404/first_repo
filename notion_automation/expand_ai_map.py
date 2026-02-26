import requests
import json

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
GUIDE_PAGE_ID = "313eacc8-175a-81fd-93d5-d90dbc0b7285" 

mindmap_blocks = [
    {
        "object": "block",
        "type": "divider",
        "divider": {}
    },
    {
        "object": "block",
        "type": "heading_1",
        "heading_1": {
            "rich_text": [{"type": "text", "text": {"content": "🧠 AI 지식의 총체: 마인드맵형 통합 가이드"}}]
        }
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": "이 체계도는 AI의 '뇌'와 '팔다리'가 어떻게 연결되는지 보여줍니다."}, "annotations": {"italic": True}}]
        }
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "1. 기초 인프라 (The Engine)"}}]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "토큰(Token): "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "AI가 글자를 이해하는 최소 단위. 효율적인 명령이 비용과 정확도를 결정합니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "컨텍스트 윈도우: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "AI의 단기 기억 용량. 대화가 길어지면 중요한 규칙(온톨로지)을 수시로 복습시켜야 합니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "2. 도구와 실행 (The Arms)"}}]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Tool Use: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "정해진 기능만 쓰는 방식 (예: 기본 노션 편집 도구)."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Code Interpreter: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "AI가 직접 코드를 짜서 API를 제어하는 방식. 무한한 확장이 가능합니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "3. 인지적 체계 (The Brain)"}}]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "온톨로지(Ontology): "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "AI에게 가르치는 '개념 사이의 관계'. (예: 수정 = 기존 보존 + 새로운 삽입)"}}
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "지식 그래프: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "개별 데이터를 거대한 그물망으로 연결해 복합적인 추론을 가능케 하는 구조입니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "4. 실전 전략 (The Strategy)"}}]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "RAG: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "AI가 외부 파일이나 문서를 실시간으로 검색해 지식의 오차를 줄이는 기술."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "Agentic Workflow: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "질문 하나로 끝내는 게 아니라, '계획-실행-검토'의 반복을 유도해 완벽한 결과물을 얻는 법."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "🏆"},
            "color": "purple_background",
            "rich_text": [
                {"type": "text", "text": {"content": "AI 마스터의 길: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "AI를 '전지전능한 신'으로 보지 말고, '엄청나게 똑똑하지만 명령을 명확히 주어야 하는 유능한 비서'로 대우하세요. 적절한 도구(API)와 가이드라인(온톨로지)을 주면 불가능은 없습니다."}}
            ]
        }
    }
]

patch_url = f"https://api.notion.com/v1/blocks/{GUIDE_PAGE_ID}/children"
res = requests.patch(patch_url, headers=HEADERS, json={"children": mindmap_blocks})
if res.status_code == 200:
    print("Successfully updated the AI Knowledge Map.")
else:
    print("Failed:", res.text)
