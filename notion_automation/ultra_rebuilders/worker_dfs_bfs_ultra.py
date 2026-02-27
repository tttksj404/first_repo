import requests
import json
import time

# 1. API Configuration

import os

def _get_notion_token():
    # Try multiple paths to find notion_key.txt
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(current_dir, 'notion_key.txt'),
        os.path.join(current_dir, '..', 'core', 'notion_key.txt'),
        os.path.join(current_dir, 'core', 'notion_key.txt'),
        os.path.join(os.getcwd(), 'notion_automation', 'core', 'notion_key.txt')
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                token = f.read().strip()
                if token: return token
    return os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")

NOTION_TOKEN = _get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PAGE_ID = "2f0eacc8-175a-805c-85b2-dca59899d3d8"

def append_blocks_safely(block_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    # Sending 3 blocks at a time for maximum stability
    for idx, i in enumerate(range(0, len(blocks), 3)):
        chunk = blocks[i:i+3]
        res = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if res.status_code == 200:
            print(f"--- Chunk {idx+1} Deployed ---")
        else:
            print(f"FAILED: {res.text}")
        time.sleep(1)

# Ultra-Detailed Data
data = [
    {
        "title": "📍 [BJ 1260] DFS와 BFS (Deep Dive)",
        "code": "# 1. 그래프 초기화: 작은 번호 우선 방문을 위한 sort() 필수\\n# 2. DFS: 재귀를 통한 수직 탐색 (LIFO)\\n# 3. BFS: 큐(deque)를 통한 수평 탐색 (FIFO)\\n\\nimport sys\\nfrom collections import deque\\n\\nn, m, v = map(int, sys.stdin.readline().split())\\ngraph = [[] for _ in range(n + 1)]\\nfor _ in range(m):\\n    a, b = map(int, sys.stdin.readline().split())\\n    graph[a].append(b); graph[b].append(a)\\n\\nfor i in range(1, n + 1): graph[i].sort()\\n\\ndef dfs(c):\\n    v_dfs[c] = True; print(c, end=' ')\\n    for n in graph[c]:\\n        if not v_dfs[n]: dfs(n)\\n\\ndef bfs(s):\\n    q = deque([s]); v_bfs[s] = True\\n    while q:\\n        c = q.popleft(); print(c, end=' ')\\n        for n in graph[c]:\\n            if not v_bfs[n]: v_bfs[n] = True; q.append(n)\\n\\nv_dfs = [False]*(n+1); v_bfs = [False]*(n+1)\\ndfs(v); print(); bfs(v)",
        "logic": "🏗️ 핵심 로직 상세:\\n- **정렬의 이유**: BFS/DFS 모두 갈림길에서 '작은 번호'부터 가야 하므로 `graph[i].sort()`가 필수.\\n- **방문 체크 시점**: BFS는 중복 큐 삽입 방지를 위해 '넣기 직전'에 방문 체크를 합니다."
    },
    {
        "title": "📍 [BJ 2178] 미로 탐색 (Deep Dive)",
        "code": "# 1. 최단 거리 측정: 가중치가 1일 때는 무조건 BFS\\n# 2. visited 대신 maze 배열에 직접 거리 누적\\n\\nfrom collections import deque\\nn, m = map(int, input().split())\\nmaze = [list(map(int, input())) for _ in range(n)]\\n\\ndef bfs():\\n    q = deque([(0, 0)])\\n    dx, dy = [-1, 1, 0, 0], [0, 0, -1, 1]\\n    while q:\\n        cx, cy = q.popleft()\\n        for i in range(4):\\n            nx, ny = cx + dx[i], cy + dy[i]\\n            if 0 <= nx < n and 0 <= ny < m and maze[nx][ny] == 1:\\n                maze[nx][ny] = maze[cx][cy] + 1 # 이전 칸 + 1\\n                q.append((nx, ny))\\n    return maze[n-1][m-1]\\n\\nprint(bfs())",
        "logic": "🏗️ 핵심 로직 상세:\\n- **BFS의 필연성**: 미로 찾기 같은 '최단 경로' 문제는 깊이 우선인 DFS보다 너비 우선인 BFS가 압도적으로 유리.\\n- **누적 거리**: `maze[nx][ny] = maze[cx][cy] + 1` 로직을 통해 1이었던 길을 2, 3, 4... 로 바꿔나가며 거리를 잽니다."
    }
]

def update():
    blocks = []
    blocks.append({"type": "divider", "divider": {}})
    blocks.append({"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "📚 [Deep Dive] 알고리즘 심층 분석 연구소"}}]}})
    
    for item in data:
        blocks.append({"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": item['title']}}]}})
        blocks.append({"type": "code", "code": {"language": "python", "rich_text": [{"text": {"content": item['code']}}]}})
        blocks.append({"type": "callout", "callout": {
            "icon": {"emoji": "🔍"},
            "color": "blue_background",
            "rich_text": [{"text": {"content": item['logic']}}]
        }})
        blocks.append({"type": "divider", "divider": {}})
    
    append_blocks_safely(PAGE_ID, blocks)

if __name__ == "__main__":
    update()
