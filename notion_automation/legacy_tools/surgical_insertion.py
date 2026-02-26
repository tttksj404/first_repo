# -*- coding: utf-8 -*-
import requests
import json

TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def insert_blocks(page_id, blocks, after_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    payload = {
        "children": blocks,
        "after": after_id
    }
    requests.patch(url, json=payload, headers=HEADERS)

if __name__ == "__main__":
    page_id = "2f0eacc8-175a-805c-85b2-dca59899d3d8"
    
    # 1. 제목(Index 0) 바로 뒤에 목차와 인트로 삽입
    # after_id: 2f0eacc8-175a-8083-b095-c14951296b30 (Heading 1 ID)
    intro_blocks = [
        {"object": "block", "type": "table_of_contents", "table_of_contents": {}},
        {"object": "block", "type": "callout", "callout": {
            "rich_text": [{"text": {"content": "💡 이 페이지는 사용자님이 정리하신 정석 코드들을 기반으로, 제가 공부하며 깨달은 팁들을 중간중간 덧붙여 만든 종합 학습장입니다. 기존 내용은 그대로 보존되어 있으니 안심하고 학습하세요!"}}],
            "icon": {"emoji": "🎓"}
        }},
        {"object": "block", "type": "divider", "divider": {}}
    ]
    print("Inserting Table of Contents and Intro...")
    insert_blocks(page_id, intro_blocks, "2f0eacc8-175a-8083-b095-c14951296b30")

    # 2. DFS 섹션(Index 10) 앞에 브릿지 삽입
    # after_id: 2f0eacc8-175a-806c-9250-fbfecc99d3cd (Divider before DFS)
    dfs_bridge = [
        {"object": "block", "type": "callout", "callout": {
            "rich_text": [{"text": {"content": "🔍 여기서부터는 DFS의 영역입니다. 스택이나 재귀를 사용하여 깊게 들어가는 탐색의 정수를 느껴보세요."}}],
            "icon": {"emoji": "⛏️"}
        }}
    ]
    print("Inserting DFS Bridge...")
    insert_blocks(page_id, dfs_bridge, "2f0eacc8-175a-806c-9250-fbfecc99d3cd")

    # 3. BFS 섹션(Index 81) 앞에 브릿지 삽입
    # after_id: 2f0eacc8-175a-80e2-b982-c4bb476856ff (Divider before BFS)
    bfs_bridge = [
        {"object": "block", "type": "callout", "callout": {
            "rich_text": [{"text": {"content": "🌊 이제 BFS로 넘어갑니다. 큐(Queue)를 사용하여 물결처럼 퍼져나가는 최단 거리 탐색을 시작합니다."}}],
            "icon": {"emoji": "🌊"}
        }}
    ]
    print("Inserting BFS Bridge...")
    insert_blocks(page_id, bfs_bridge, "2f0eacc8-175a-80e2-b982-c4bb476856ff")

    print("Surgical Insertion Complete!")
