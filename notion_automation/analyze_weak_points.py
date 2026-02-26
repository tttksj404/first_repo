import requests
import json

NOTION_TOKEN = "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"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

PAGES = {
    "DFS/BFS": "2f0eacc8-175a-805c-85b2-dca59899d3d8",
    "스택큐": "2eaeacc8-175a-80fa-98b4-e0a61bda22cb"
}

def update_page(page_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    res = requests.patch(url, headers=HEADERS, json={"children": blocks})
    return res.status_code

# DFS/BFS Data
dfs_blocks = [
    {"object": "block", "type": "divider", "divider": {}},
    {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "⚠️ [실수 방지] DFS/BFS 오답 노트 & 최종 체크리스트"}}]}},
    {"object": "block", "type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "🚫"},
        "color": "red_background",
        "rich_text": [{"type": "text", "text": {"content": "가장 많이 했던 실수: 인덱스 범위 초과(*2 연산 시), count 변수 오용(단순 pop 횟수 세기), 시작점 예외 처리 누락."}}]
    }},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "인덱스 체크: if 0 <= next < MAX_SIZE 조건을 큐에 넣기 직전에 반드시 확인했는가?"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "거리 측정: visited[next] = visited[curr] + 1 공식을 사용했는가?"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "N == K: 시작하자마자 끝나는 경우(0초)를 코드 맨 위에 넣었는가?"}}]}},
    {"object": "block", "type": "divider", "divider": {}}
]

# Stack/Queue Data
sq_blocks = [
    {"object": "block", "type": "divider", "divider": {}},
    {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "⚠️ [실수 방지] Stack/Queue 오답 노트 & 최종 체크리스트"}}]}},
    {"object": "block", "type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "🚫"},
        "color": "red_background",
        "rich_text": [{"type": "text", "text": {"content": "가장 많이 했던 실수: 비어있는 스택에서 pop 시도, 인덱스 에러, while문 조건 설정 실수."}}]
    }},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "Empty Check: pop()이나 top 참조 전 if stack: 으로 비어있는지 확인했는가?"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "Queue 효율성: list.pop(0) 대신 collections.deque의 popleft()를 사용했는가?"}}]}},
    {"object": "block", "type": "divider", "divider": {}}
]

update_page(PAGES["DFS/BFS"], dfs_blocks)
update_page(PAGES["스택큐"], sq_blocks)
print("Updated all pages.")
