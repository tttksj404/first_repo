import requests
import json

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
GUIDE_PAGE_ID = "313eacc8-175a-81fd-93d5-d90dbc0b7285" 

additional_blocks = [
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "🌍 4. 이 방법이 다른 API에도 통용되나요?"}}]
        }
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": "네, 100% 통용됩니다. 거의 모든 현대 IT 서비스는 'REST API'라는 공용어를 사용하기 때문입니다."}}]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "보편적 연결: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "GitHub, Slack, AWS 등 어떤 서비스든 AI에게 '스크립트로 API를 직접 호출해'라고 명령하면 도구의 한계를 넘어 무한한 확장이 가능합니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": "🧠 5. AI를 지배하는 3단계 마인드셋"}}]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "1단계 (Captain Mindset): "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "AI는 조종간을 잡은 Pilot일 뿐입니다. 항로(가독성, 형식)는 사용자가 결정하고, 맘에 안 들면 즉시 수정을 명령해야 합니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "2단계 (Chain of Thought): "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "\"내 요구사항을 먼저 요약해봐\"라고 명령하여 AI와 사용자의 '의도'가 일치하는지 확인하세요."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "3단계 (Self-Correction): "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "\"네가 짠 코드를 스스로 다시 검토해봐\"라고 덧붙이면 할루시네이션(거짓말)을 획기적으로 줄일 수 있습니다."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "⚠️"},
            "color": "yellow_background",
            "rich_text": [
                {"type": "text", "text": {"content": "보안 철칙: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "API 토큰은 절대 코드에 직접 노출하지 마세요. 안전한 곳(settings.json 등)에 보관하고 AI가 이를 참조하게 하는 것이 프로 개발자의 방식입니다."}}
            ]
        }
    }
]

patch_url = f"https://api.notion.com/v1/blocks/{GUIDE_PAGE_ID}/children"
res = requests.patch(patch_url, headers=HEADERS, json={"children": additional_blocks})
if res.status_code == 200:
    print("Successfully updated.")
else:
    print("Failed:", res.text)
