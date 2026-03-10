import requests
import json
import time
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def delete_blocks(block_ids):
    for bid in block_ids:
        url = f"https://api.notion.com/v1/blocks/{bid}"
        requests.delete(url, headers=HEADERS)
        time.sleep(0.1)

def append_blocks(block_id, children):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    res = requests.patch(url, headers=HEADERS, json={"children": children})
    return res.status_code == 200

def main():
    parent_page_id = "2f0eacc8-175a-8072-8e4b-e298edcb69c5"
    
    # 1. Fetch current blocks to identify what to keep/remove
    # Based on previous fetch, I'll remove most redundant theory blocks and structure it properly.
    # Actually, it's easier to just archive everything and rewrite it, but I'll try to be surgical.
    
    # Let's just delete the messy theory sections and the duplicated Samsung roadmap.
    # Section 1: 2f0eacc8-175a-80e1-a9f1-fbdb45558a87 (H1: 재귀 알고리즘 스터디)
    # Section 2: 310eacc8-175a-8000-a13c-eb384193b581 (H1: 삼성 A형 정복...)
    
    # I'll delete almost everything and put a clean structure.
    # Block IDs from get_parent_blocks.py:
    all_blocks_to_delete = [
        "303eacc8-175a-80e2-a533-db867dcec53b", "312eacc8-175a-81a5-b533-e02187c03336",
        "312eacc8-175a-8152-b2ce-d13080bdc21b", "312eacc8-175a-810f-b591-cc43928fc2cb",
        "2f0eacc8-175a-80d1-9ff2-f64aca87ef46", "303eacc8-175a-8061-899e-ed5c68c80dd4",
        "303eacc8-175a-80dc-a526-cc4e0d559edb", "303eacc8-175a-8042-a00a-cb342d88193e",
        "2f0eacc8-175a-80e1-a9f1-fbdb45558a87", "2f0eacc8-175a-8010-8cce-cfcbbf3b36ee",
        "2f0eacc8-175a-8043-8465-cc242209ad60", "2f0eacc8-175a-80c9-ac82-f044b2f12c16",
        "2f0eacc8-175a-8062-a9c8-cdc11189928c", "2f0eacc8-175a-809e-8d46-e30f379c3ce0",
        "2f0eacc8-175a-800f-8454-e22dd9c5ec5c", "302eacc8-175a-808b-9120-e27d87249fba",
        "2f0eacc8-175a-8028-98e1-db7073e1baf6", "2f0eacc8-175a-807a-a877-fe0e2d568353",
        "2f0eacc8-175a-8074-b8f2-fce147cc00bc", "2f0eacc8-175a-8096-9f33-c7f318bedd22",
        "2f0eacc8-175a-8069-b4e3-d4f33285e5b8", "2f0eacc8-175a-80b2-9cbb-c3786824a0a7",
        "2f0eacc8-175a-8067-834f-c877b5b1be77", "2f0eacc8-175a-80fa-8070-e4b57c0711bf",
        "2f0eacc8-175a-802c-b9d8-c9a2bb791cbe", "2f0eacc8-175a-8052-97f3-eb71b522ccd7",
        "2f0eacc8-175a-80d2-a72a-f62d3b9d6c72", "2f0eacc8-175a-8049-9cf7-e8f86e91d145",
        "2f0eacc8-175a-8000-b0ff-ef2e0930ffdc", "2f0eacc8-175a-804e-bdd8-df69dcaccbf1",
        "2f0eacc8-175a-80f1-b4ed-cffbd5daa0f3", "2f0eacc8-175a-803d-90a1-d6fdee147863",
        "2f0eacc8-175a-807a-9c2e-def956ddc8d4", "2f0eacc8-175a-80d9-99fc-fbaa24dd2467",
        "2f0eacc8-175a-806b-8bbc-c9bb989bde73", "2f0eacc8-175a-8027-b847-eefa4edf627d",
        "2f0eacc8-175a-8064-befd-c07bed8400ae", "2f0eacc8-175a-80dd-97e6-e11bae143985",
        "2f0eacc8-175a-80fa-9e58-ccb3c5e9bf7d", "2f0eacc8-175a-801d-a3a1-c505991ce7b5",
        "2f0eacc8-175a-80d6-b6c2-e6cc9ef385e2", "2f0eacc8-175a-8053-ac7f-c53239090ad3",
        "2f0eacc8-175a-806d-84b1-cca4b3f3a4ce", "2f0eacc8-175a-8009-a289-edf22680c3d6",
        "2f0eacc8-175a-80a4-8f5d-fbc2237a7fb9", "2f0eacc8-175a-809b-a32c-da8cd7d65acc",
        "2f0eacc8-175a-805b-9b60-da5b897b5e41", "2f0eacc8-175a-80f1-b88a-e898b463d197",
        "2f0eacc8-175a-8026-85bc-c83875f542c4", "2f0eacc8-175a-8046-8771-e2e2c7f363db",
        "2f0eacc8-175a-80af-a868-c296adb164c1", "2f0eacc8-175a-8099-95ab-dc4f58a02344",
        "2f0eacc8-175a-804f-b91b-df96f0d80f91", "2f0eacc8-175a-8077-9897-e7091947b340",
        "2f4eacc8-175a-8084-a907-d3b2e07da4cc", "2f4eacc8-175a-802c-85e7-e75bcebcbb0b",
        "2f4eacc8-175a-807b-a9b9-db1b3ba1e23a", "2f4eacc8-175a-80ac-b8f7-cf2a55e1fd9a",
        "2f4eacc8-175a-8089-8d67-c82e5087ef37", "310eacc8-175a-8056-81c5-d81e432a2501",
        "310eacc8-175a-809b-8720-c007eae5760e", "310eacc8-175a-8000-a13c-eb384193b581",
        "310eacc8-175a-8015-a485-c37ea386ee40", "310eacc8-175a-8009-93e7-d5ffa8d99d0c",
        "310eacc8-175a-80af-83f2-f6655179c2ce", "310eacc8-175a-8045-93c4-e52834727c5a",
        "310eacc8-175a-80ad-94a6-f591be12dde8", "310eacc8-175a-802c-8704-e850f57ad2a2",
        "310eacc8-175a-8051-b0d1-ee709a9676af", "310eacc8-175a-80aa-9c83-e539dbe19c53",
        "310eacc8-175a-805d-aa4e-f3eab4851bb9", "312eacc8-175a-8169-be9a-e4c44e6f891d",
        "312eacc8-175a-8199-992d-d6b7659c2f09", "312eacc8-175a-8168-bcf7-ed9c2b5020a9"
    ]
    
    print(f"Deleting {len(all_blocks_to_delete)} blocks...")
    # Delete in chunks to avoid timeout
    for i in range(0, len(all_blocks_to_delete), 10):
        delete_blocks(all_blocks_to_delete[i:i+10])
    
    # 2. Append new clean structure
    masterbook_id = "31feacc8175a815cab4bcc5da3b4d039"
    strategy_page_id = "31beacc8175a813cba9bc0ff8e8d5d98"
    
    new_blocks = [
        {
            "object": "block",
            "type": "heading_1",
            "heading_1": {"rich_text": [{"type": "text", "text": {"content": "🚀 삼성 A형 정복: 재귀 & 백트래킹 마스터 허브"}}] }
        },
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": "이 페이지는 재귀 알고리즘의 기초부터 삼성 A형 실전 전략까지 연결하는 중앙 허브입니다."}}],
                "icon": {"emoji": "🎯"}
            }
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📚 핵심 학습 리소스 (Single Source of Truth)"}}] }
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    {"type": "text", "text": {"content": "📕 "}},
                    {"type": "text", "text": {"content": "[마스터북] 백트래킹 3대 천왕", "link": {"url": f"https://www.notion.so/{masterbook_id}"}}},
                    {"type": "text", "text": {"content": ": 순열, 조합, 부분집합 표준 템플릿 및 기본 문제"}}
                ]
            }
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    {"type": "text", "text": {"content": "📍 "}},
                    {"type": "text", "text": {"content": "DFS & 백트래킹 극한정복 (Strategy)", "link": {"url": f"https://www.notion.so/{strategy_page_id}"}}},
                    {"type": "text", "text": {"content": ": 격자 탐색, 가지치기, 가중치 DFS 등 실전 필살기"}}
                ]
            }
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📅 단계별 학습 로드맵"}}] }
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": "Step 1: 재귀 기초 (스택 프레임, 변수 스코프 이해)"}}]
            }
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": "Step 2: 기본 유형 마스터 (순열/조합/부분집합 템플릿 암기)"}}]
            }
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": "Step 3: 격자 및 상태 관리 (방향 벡터, 방문 배열, 상태 복구)"}}]
            }
        },
        {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": "Step 4: 심화 전략 (가지치기, 최적화)"}}]
            }
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🧠 필수 문제 리스트 (Checklist)"}}] }
        }
        # Individual problems will stay as child pages at the bottom (they weren't deleted)
    ]
    
    if append_blocks(parent_page_id, new_blocks):
        print("Successfully reorganized Parent page")
    else:
        print("Failed to reorganize Parent page")

if __name__ == "__main__":
    main()
