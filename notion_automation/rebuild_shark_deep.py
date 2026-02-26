import requests
import json
import time

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def rebuild_page(pid, title, blocks):
    # 1. Clear existing
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
    # 2. Patch new
    requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": blocks})

# 2. [Samsung A] 아기 상어 - IM 초격차 상세 버전
shark_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Samsung A] 아기 상어 - 우선순위 BFS 및 성장 시뮬레이션"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "문제 요약: $N 	imes N$ 공간에서 아기 상어가 물고기를 잡아먹으며 이동하는 시간을 구합니다. 핵심은 상어의 크기 변화와 '동일 거리 시 상단/좌측 우선'이라는 복합 조건 처리입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "1. 2차원 배열 정복 (Grid Mastery)"}}]}},
    {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "상어의 이동은 전형적인 델타 탐색 기반의 BFS입니다. 하지만 단순히 목적지에 도달하는 것이 아니라, 매 순간 '먹을 수 있는 모든 물고기'를 탐색해야 합니다."}}]}},
    {"type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": "① 다중 우선순위 조건 (Priority Search)"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "핵심 로직"}, "annotations": {"bold": True}}, {"type": "text", "text": ": BFS 탐색 중 현재 상어 크기보다 작은 물고기를 발견하면 후보 리스트에 (거리, r, c) 형태로 저장합니다. 탐색이 끝난 후 이 리스트를 정렬하여 최우선 대상을 선정합니다."}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "활용 기술"}, "annotations": {"bold": True}}, {"type": "text", "text": ": candidates.sort(key=lambda x: (x[0], x[1], x[2]))"}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "2. 논리적 상태 관리 (State Management)"}}]}},
    {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "상어의 상태(현재 크기, 지금까지 먹은 물고기 수)를 변수로 관리하며, 성장 조건을 실시간으로 체크해야 합니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "성장 공식"}, "annotations": {"bold": True}}, {"type": "text", "text": ": if eat_count == shark_size: shark_size += 1; eat_count = 0"}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 Python 초정밀 실전 코드"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''from collections import deque

def bfs(start_r, start_c, size):
    q = deque([(start_r, start_c, 0)])
    visited = [[False]*N for _ in range(N)]
    visited[start_r][start_c] = True
    candidates = []
    
    while q:
        r, c, dist = q.popleft()
        for i in range(4):
            nr, nc = r+dr[i], c+dc[i]
            if 0<=nr<N and 0<=nc<N and not visited[nr][nc]:
                if grid[nr][nc] <= size: # 이동 가능
                    visited[nr][nc] = True
                    if 0 < grid[nr][nc] < size: # 먹기 가능
                        candidates.append((dist+1, nr, nc))
                    else:
                        q.append((nr, nc, dist+1))
    # 1.거리 2.행 3.열 순으로 정렬된 리스트 반환
    return sorted(candidates)'''}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "5. 시험장 필살 체크리스트 (Cheat-Sheet)"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "먹을 물고기를 찾은 후 상어의 위치를 해당 물고기 칸으로 옮기고, 그 칸은 빈칸(0)으로 만들었는가?"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "먹을 물고기가 더 이상 없을 때의 종료 조건을 정확히 설정했는가?"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "한 번 이동할 때마다 방문 배열(visited)을 초기화했는가?"}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: '거리가 같은 경우'라는 조건이 보이면 BFS 내부에서 즉시 리턴하지 말고, 같은 거리의 모든 노드를 다 본 뒤 정렬하는 것이 IM 이상의 실력자가 되는 지름길입니다."}}]
    }}
]

rebuild_page("313eacc8-175a-81e5-a57e-d33266fd300c", "📍 [Samsung A] 아기 상어", shark_blocks)
print("Shark page rebuilt with high detail.")
