import requests
import json
import time

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

PAGES = {
    "taxi": "313eacc8-175a-81f8-b518-fbfea3edcac5",
    "newgame2": "313eacc8-175a-81a1-b46f-d1de909db499",
    "insertops": "313eacc8-175a-81d1-b45c-ff132d0b1f56"
}

taxi_blocks = [
    {"object": "block", "type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 20] 스타트 택시 - 복합 BFS와 우선순위 시뮬레이션"}}]}},
    {"object": "block", "type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "승객을 찾아 목적지까지 운송하며 연료를 관리하는 복합 시뮬레이션입니다. 승객 선택 시의 우선순위 조건(최단거리, 행 번호, 열 번호)과 연료 충전/소모 계산이 핵심입니다."}}]}},
    {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "목표: "}, "annotations": {"bold": True}}, {"type": "text", "text": "모든 승객을 성공적으로 데려다주었을 때 남은 연료의 양을 구하라."}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "우선순위: "}, "annotations": {"bold": True}}, {"type": "text", "text": "1. 최단거리 승객 -> 2. 행 번호가 작은 승객 -> 3. 열 번호가 작은 승객"}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "연료 규칙: "}, "annotations": {"bold": True}}, {"type": "text", "text": "이동 시 연료 1 소모, 승객 운송 성공 시 (소모한 연료 * 2) 충전. 도중 연료 0 되면 실패."}]}},
    {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "현실 로직: "}, "annotations": {"bold": True}}, {"type": "text", "text": "현재 내 위치에서 가장 가까운 손님을 고른다. 손님이 여럿이면 북서쪽에 있는 분부터 모신다. 기름이 떨어지지 않게 조심하며 목적지까지 모셔다 드리고 보너스 기름을 받는다."}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "코딩 로직: "}, "annotations": {"bold": True}}, {"type": "text", "text": "1. 승객 탐색 BFS (모든 승객까지의 거리 계산). 2. 승객 선정 (정렬). 3. 목적지 이동 BFS (연료 체크 및 충전)."}]}},
    {"object": "block", "type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''def get_dist(start_node):
    q = deque([start_node])
    dist_map = [[-1]*N for _ in range(N)]
    dist_map[start_node[0]][start_node[1]] = 0
    while q:
        r, c = q.popleft()
        for i in range(4):
            nr, nc = r+dr[i], c+dc[i]
            if 0<=nr<N and 0<=nc<N and grid[nr][nc] != 1 and dist_map[nr][nc] == -1:
                dist_map[nr][nc] = dist_map[r][c] + 1
                q.append((nr, nc))
    return dist_map'''}}]}},
    {"object": "block", "type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "🎓"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 승객 위치까지 가는 길이나 목적지까지 가는 길이 벽으로 막혀 있어 도달 불가능한 경우를 반드시 예외 처리(-1 반환) 하세요. 연료가 딱 0이 되어 도착하는 것은 성공이지만, 이동 도중에 0이 되는 것은 실패입니다."}}]
    }}
]

for pid, blocks in [ (PAGES["taxi"], taxi_blocks) ]:
    requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": blocks})

print("Fixed empty page.")
