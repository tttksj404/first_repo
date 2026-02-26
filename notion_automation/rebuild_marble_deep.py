import requests
import json
import time

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def update_page(pid, blocks):
    # Fetch and delete existing children to rebuild from scratch
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
    # Patch new children blocks
    requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": blocks})

# Rebuilding Marble Escape 2
marble_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 04] 구슬 탈출 2 - 4차원 BFS 및 물리 시뮬레이션"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "빨간 구슬을 구멍에 넣고 파란 구슬은 막는 10회 제한 시뮬레이션입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "1. 핵심 구현 로직"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "4D Visited: "}, "annotations": {"bold": True}}, {"type": "text", "text": "visited[rx][ry][bx][by]를 사용하여 동일 상태 재방문을 막습니다."}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "중첩 보정: "}, "annotations": {"bold": True}}, {"type": "text", "text": "두 구슬이 한 칸에 멈추면, 이동거리가 더 먼 구슬을 반대 방향으로 한 칸 보정합니다."}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''def move(r, c, dr, dc):
    cnt = 0
    while grid[r+dr][c+dc] != '#' and grid[r][c] != 'O':
        r += dr; c += dc; cnt += 1
    return r, c, cnt'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 파란 구슬 탈출 여부를 먼저 체크하세요. 동시에 탈출하는 것도 실패 조건입니다."}}]
    }}
]

update_page("313eacc8-175a-8108-9c3a-f2fa6658f3b0", marble_blocks)
print("Marble page rebuilt.")
