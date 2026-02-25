# -*- coding: utf-8 -*-
import requests
import json
import sys

TOKEN = "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"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def delete_blocks(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    res = requests.get(url, headers=HEADERS).json()
    for block in res.get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{block['id']}", headers=HEADERS)

def append_blocks(page_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    requests.patch(url, json={"children": blocks}, headers=HEADERS)

# Updated structured content without problematic comments in Python strings
REMODELED_CONTENT = [
    {"object": "block", "type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🏆 알고리즘 마스터: DFS & BFS 탐색"}}]}},
    {"object": "block", "type": "callout", "callout": {
        "rich_text": [{"text": {"content": "그래프 탐색의 양대 산맥! 모든 노드를 방문하는 것은 같지만, '어떤 순서'로 방문하느냐가 핵심입니다."}}],
        "icon": {"emoji": "🗺️"}
    }},
    {"object": "block", "type": "divider", "divider": {}},
    
    {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "1️⃣ 기초 다지기: 자료구조와 방문 처리 (Visited)"}}]}},
    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "알고리즘에서 '방문 처리'는 무한 루프(Cycle)를 방지하고 메모리 낭비를 줄이는 가장 기본이자 핵심 장치입니다."}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 인접 행렬(Matrix) vs 인접 리스트(List): 노드 개수가 많을 땐 인접 리스트가 유리해요!"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 Visited 배열의 역할: 중복 방문 제거 및 경로의 유일성 보장"}}]}},
    
    {"object": "block", "type": "divider", "divider": {}},
    
    {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "2️⃣ DFS (깊이 우선 탐색) - '끝까지 가보자!'"}}]}},
    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "한 방향으로 갈 수 있는 데까지 깊게 들어갔다가, 더 이상 갈 곳이 없으면 뒤로 돌아와(Backtrack) 다른 길을 찾는 방식입니다."}}]}},
    {"object": "block", "type": "callout", "callout": {
        "rich_text": [{"text": {"content": "학생 꿀팁: DFS는 주로 '재귀(Recursion)'로 구현하면 코드가 아주 깔끔해져요. 단, Python에서는 sys.setrecursionlimit()을 꼭 기억하세요!"}}],
        "icon": {"emoji": "💡"}
    }},
    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "💻 [실전] 단지 번호 붙이기 & 백트래킹"}}]}},
    {"object": "block", "type": "code", "code": {
        "language": "python",
        "rich_text": [{"text": {"content": "dx = [-1, 1, 0, 0]\ndy = [0, 0, -1, 1]\n\ndef dfs(x, y):\n    visited[x][y] = True\n    size = 1\n    for i in range(4):\n        nx, ny = x + dx[i], y + dy[i]\n        if 0 <= nx < n and 0 <= ny < n:\n            if grid[nx][ny] == 1 and not visited[nx][ny]:\n                size += dfs(nx, ny)\n    return size"}}]
    }},
    
    {"object": "block", "type": "divider", "divider": {}},
    
    {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "3️⃣ BFS (너비 우선 탐색) - '가까운 곳부터 차례대로!'"}}]}},
    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "시작점에서 가까운 노드부터 순차적으로 탐색하는 방식입니다. '최단 거리'를 구할 때 가장 강력한 도구입니다."}}]}},
    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "🚀 [심화] 멀티소스 BFS (동시 확산)"}}]}},
    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "토마토 문제처럼 여러 지점에서 동시에 퍼져나갈 때는, 모든 시작점을 큐에 먼저 넣고 시작하는 것이 포인트!"}}]}},
    {"object": "block", "type": "code", "code": {
        "language": "python",
        "rich_text": [{"text": {"content": "from collections import deque\nqueue = deque([(0, 0, 0)])\ndist[0][0] = 1\n\nwhile queue:\n    r, c = queue.popleft()\n    if r == N-1 and c == M-1: return dist[r][c]\n    # BFS search logic..."}}]
    }},
    
    {"object": "block", "type": "divider", "divider": {}},
    {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "📝 학습 요약 및 체크리스트"}}]}},
    {"object": "block", "type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"text": {"content": "최단 거리는 BFS, 경로의 특징이 중요하다면 DFS!"}}]}},
    {"object": "block", "type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"text": {"content": "방문 처리는 큐/스택에 넣기 직전에 하는 것이 가장 안전함."}}]}},
    {"object": "block", "type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"text": {"content": "2차원 격자 탐색 시 델타 배열(dr, dc)과 범위 체크는 공식처럼 암기!"}}]}}
]

if __name__ == "__main__":
    page_id = "2f0eacc8-175a-805c-85b2-dca59899d3d8"
    print("Redesigning the page with original logic and improved layout...")
    delete_blocks(page_id)
    append_blocks(page_id, REMODELED_CONTENT)
    print("Remodeling complete!")
