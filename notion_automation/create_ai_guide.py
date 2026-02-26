import requests
import json

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
# Set parent to "코테 대비" page
PARENT_PAGE_ID = "303eacc8-175a-80a3-9154-f7a7acee7c80" 

content_blocks = [
    {
        "object": "block",
        "type": "heading_1",
        "heading_1": {
            "rich_text": [{"type": "text", "text": {"content": "🚀 CLI AI 활용 가이드: 내부 메커니즘과 필승 명령법"}}]
        }
    },
    {
        "object": "block",
        "type": "quote",
        "quote": {
            "rich_text": [{"type": "text", "text": {"content": "AI(에이전트)를 단순한 챗봇이 아닌, 시스템을 직접 제어하는 강력한 도구로 활용하기 위한 심화 가이드입니다."}}]
        }
    },
    {
        "object": "block",
        "type": "divider",
        "divider": {}
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "1. 왜 처음엔 노션 기능을 100% 사용하지 못했나요?"}}]
        }
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": "비밀은 '도구(Tool) 규격'과 '직접 제어(Scripting)'의 차이에 있습니다."}}]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "제한된 도구(Predefined Tool): "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "제가 기본으로 가진 'Notion Tool'은 안전을 위해 텍스트와 리스트만 쓰도록 설계되었습니다. 그래서 코드 블록이나 콜아웃을 넣으려 하면 에러가 뜬 것입니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "파이썬 스크립트 실행(Direct API): "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "하지만 파이썬으로 API를 직접 호출하면 중간 제약 없이 노션의 모든 기능을 100% 사용할 수 있습니다. AI에게 '스크립트로 해결해!'라고 명령하는 것이 핵심입니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "2. 온톨로지(Ontology)와 AI의 사고 방식"}}]
        }
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": "온톨로지는 AI가 세상을 이해하는 '개념의 지도'입니다."}}]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "정의와 분류: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "AI가 '코드 블록'을 단순 텍스트로 볼지, 아니면 '특수한 시각적 도구'로 볼지는 AI의 온톨로지 설정에 달려 있습니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "관계의 이해: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "\"내용을 수정할 때는 기존 내용을 절대 지우지 않는다\"는 규칙은 AI의 행동 온톨로지에 각인되어 의사결정의 기준이 됩니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "3. AI를 200% 활용하는 필승 명령법"}}]
        }
    },
    {
        "object": "block",
        "type": "code",
        "code": {
            "language": "markdown",
            "rich_text": [{"type": "text", "text": {"content": "1. 역할 부여: \"너는 노션 API 전문가이자 파이썬 개발자야.\"\n2. 구체적 제약: \"기존 문서의 Bold, Quote 스타일을 100% 복제해.\"\n3. 도구 지정: \"도구가 한계라면 직접 Python 스크립트를 실행해.\"\n4. 예시 제공: \"Problem 01의 코드 블록 형식을 참고해.\""}}]
        }
    },
    {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "💡"},
            "color": "blue_background",
            "rich_text": [
                {"type": "text", "text": {"content": "공부하는 학생의 시점: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "AI는 시키는 대로만 하는 비서가 아니라, 적절한 도구와 데이터를 주면 직접 정답을 만들어내는 '전문가'입니다. AI의 내부 작동 원리를 역이용하세요!"}}
            ]
        }
    },
    {
        "object": "block",
        "type": "divider",
        "divider": {}
    }
]

new_page_data = {
    "parent": {"page_id": PARENT_PAGE_ID},
    "properties": {
        "title": [{"text": {"content": "📚 AI 활용 가이드: 똑똑하게 명령하고 200% 활용하기"}}]
    },
    "children": content_blocks
}

create_url = "https://api.notion.com/v1/pages"
res = requests.post(create_url, headers=HEADERS, json=new_page_data)
if res.status_code == 200:
    print(f"Successfully created: {res.json()['url']}")
else:
    print("Failed:", res.status_code, res.text)
