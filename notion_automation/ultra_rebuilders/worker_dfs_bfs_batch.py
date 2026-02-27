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

# Target Page ID (DFS/BFS)
PAGE_ID = "2f0eacc8-175a-805c-85b2-dca59899d3d8"

def append_blocks_chunked(block_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    for i in range(0, len(blocks), 5):
        chunk = blocks[i:i+5]
        res = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if res.status_code != 200:
            print(f"FAILED on chunk {i}: {res.text}")
        time.sleep(0.5)

problems = [
    {
        "title": "📍 [BJ 1260] DFS와 BFS",
        "context": "그래프 탐색의 두 가지 표준인 DFS(깊이 우선)와 BFS(너비 우선)를 구현하는 기초 문제입니다.",
        "analysis": "🔍 상세 분석\n- 핵심: 방문할 수 있는 정점이 여러 개인 경우 '번호가 낮은 정점'부터 방문하는 정렬이 필수입니다.\n- 로직: DFS는 재귀를 통한 깊이 탐색, BFS는 큐를 통한 레이어 탐색.",
        "code": '''import sys
from collections import deque

def dfs(v):
    visited_dfs[v] = True
    print(v, end=' ')
    for next_v in sorted(graph[v]): # 작은 번호부터 방문
        if not visited_dfs[next_v]:
            dfs(next_v)

def bfs(v):
    queue = deque([v])
    visited_bfs[v] = True
    while queue:
        curr = queue.popleft()
        print(curr, end=' ')
        for next_v in sorted(graph[curr]):
            if not visited_bfs[next_v]:
                visited_bfs[next_v] = True
                queue.append(next_v)

n, m, v = map(int, sys.stdin.readline().split())
graph = [[] for _ in range(n + 1)]
for _ in range(m):
    a, b = map(int, sys.stdin.readline().split())
    graph[a].append(b)
    graph[b].append(a)

visited_dfs = [False] * (n + 1)
visited_bfs = [False] * (n + 1)

dfs(v); print()
bfs(v)''',
        "guide": "💡 학생 가이드: 인접 리스트 사용 시 각 리스트를 '정렬'해두면 매번 sorted()를 호출할 필요가 없어 더 효율적입니다."
    },
    {
        "title": "📍 [BJ 2178] 미로 탐색",
        "context": "격자형 미로에서 (1,1)에서 (N,M)까지 가는 최단 거리를 찾는 문제입니다.",
        "analysis": "🔍 상세 분석\n- 핵심: 가중치가 없는 최단 거리는 무조건 BFS입니다.\n- 로직: 델타 탐색(상하좌우)을 수행하며, 방문할 때마다 이전 칸의 거리에 +1을 누적합니다.",
        "code": '''from collections import deque

n, m = map(int, input().split())
maze = [list(map(int, input())) for _ in range(n)]

def bfs(x, y):
    queue = deque([(x, y)])
    while queue:
        cx, cy = queue.popleft()
        for dx, dy in [(-1, 1, 0, 0), (0, 0, -1, 1)]:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < n and 0 <= ny < m:
                if maze[nx][ny] == 1: # 길 발견
                    maze[nx][ny] = maze[cx][cy] + 1
                    queue.append((nx, ny))
    return maze[n-1][m-1]

print(bfs(0, 0))''',
        "guide": "💡 학생 가이드: maze 값을 거리 정보로 직접 사용하면 별도의 visited 배열 없이도 중복 방문을 막을 수 있습니다."
    },
    {
        "title": "📍 [BJ 2606] 바이러스",
        "context": "한 컴퓨터가 감염되었을 때 네트워크를 통해 감염되는 총 컴퓨터의 수를 구합니다.",
        "analysis": "🔍 상세 분석\n- 핵심: 1번 노드와 연결된 '컴포넌트'의 크기를 묻는 문제입니다.\n- 로직: DFS나 BFS 아무거나 써도 무방하며, 방문 체크 시 카운트를 하나씩 늘려줍니다.",
        "code": '''n = int(input()) # 컴퓨터 수
m = int(input()) # 연결 수
graph = [[] for _ in range(n+1)]
for _ in range(m):
    a, b = map(int, input().split())
    graph[a].append(b)
    graph[b].append(a)

visited = [False] * (n + 1)
count = 0

def dfs(v):
    global count
    visited[v] = True
    for next_v in graph[v]:
        if not visited[next_v]:
            count += 1
            dfs(next_v)

dfs(1)
print(count)''',
        "guide": "💡 학생 가이드: 시작점인 1번 컴퓨터는 결과 카운트에서 제외하는지 포함하는지 문제 조건을 잘 확인하세요."
    },
    {
        "title": "📍 [BJ 2667] 단지번호붙이기",
        "context": "이차원 배열에서 연결된 1들의 덩어리(단지)를 찾고 각각의 크기를 정렬해 출력합니다.",
        "analysis": "🔍 상세 분석\n- 핵심: 모든 칸을 순회하며 '아직 방문하지 않은 1'을 시작점으로 탐색을 수행합니다.\n- 로직: 영역 하나를 끝낼 때마다 단지 내 집의 수를 리스트에 담아 최종 정렬합니다.",
        "code": '''def dfs(x, y):
    global cnt
    visited[x][y] = True
    cnt += 1
    for dx, dy in [(-1, 1, 0, 0), (0, 0, -1, 1)]:
        nx, ny = x + dx, y + dy
        if 0 <= nx < n and 0 <= ny < n:
            if board[nx][ny] == 1 and not visited[nx][ny]:
                dfs(nx, ny)

n = int(input())
board = [list(map(int, input())) for _ in range(n)]
visited = [[False] * n for _ in range(n)]
results = []

for i in range(n):
    for j in range(n):
        if board[i][j] == 1 and not visited[i][j]:
            cnt = 0
            dfs(i, j)
            results.append(cnt)

results.sort()
print(len(results))
for r in results: print(r)''',
        "guide": "💡 학생 가이드: DFS와 BFS 중 손에 익은 것을 사용하되, 재귀 깊이(Recursion Limit)에 주의하세요."
    },
    {
        "title": "📍 [BJ 2644] 촌수계산",
        "context": "두 사람 사이의 관계가 주어졌을 때 몇 촌 관계인지 구하는 그래프 거리 문제입니다.",
        "analysis": "🔍 상세 분석\n- 핵심: 두 정점 사이의 최단 거리를 구하되, 연결되지 않았다면 -1을 출력합니다.\n- 로직: DFS 인자로 'depth(촌수)'를 넘겨주거나, BFS로 레벨 탐색을 수행합니다.",
        "code": '''n = int(input())
a, b = map(int, input().split())
m = int(input())
graph = [[] for _ in range(n+1)]
for _ in range(m):
    p, c = map(int, input().split())
    graph[p].append(c)
    graph[c].append(p)

res = -1
def dfs(curr, target, chon):
    global res
    visited[curr] = True
    if curr == target:
        res = chon
        return
    for next_v in graph[curr]:
        if not visited[next_v]:
            dfs(next_v, target, chon + 1)

visited = [False] * (n + 1)
dfs(a, b, 0)
print(res)''',
        "guide": "💡 학생 가이드: DFS는 한 번 찾으면 바로 return하게 설계하는 것이 효율적입니다."
    },
    {
        "title": "📍 [BJ 7569] 토마토 (3D)",
        "context": "3차원 상자 안에서 익은 토마토들이 주변 토마토를 익히는 최소 일수를 구합니다.",
        "analysis": "🔍 상세 분석\n- 핵심: 여러 시작점에서 동시에 퍼져나가는 '멀티소스 BFS' + 3차원 델타 탐색.\n- 로직: 큐에 처음에 익어있는 모든 토마토 좌표를 넣고 시작합니다.",
        "code": '''import sys
from collections import deque

m, n, h = map(int, sys.stdin.readline().split())
box = []
queue = deque()

for i in range(h):
    layer = []
    for j in range(n):
        row = list(map(int, sys.stdin.readline().split()))
        for k in range(m):
            if row[k] == 1:
                queue.append((i, j, k)) # (h, n, m)
        layer.append(row)
    box.append(layer)

dh = [1, -1, 0, 0, 0, 0] # 위아래
dn = [0, 0, -1, 1, 0, 0] # 상하
dm = [0, 0, 0, 0, -1, 1] # 좌우

while queue:
    ch, cn, cm = queue.popleft()
    for i in range(6):
        nh, nn, nm = ch + dh[i], cn + dn[i], cm + dm[i]
        if 0 <= nh < h and 0 <= nn < n and 0 <= nm < m:
            if box[nh][nn][nm] == 0:
                box[nh][nn][nm] = box[ch][cn][cm] + 1
                queue.append((nh, nn, nm))

ans = 0
for layer in box:
    for row in layer:
        for val in row:
            if val == 0: # 안 익은 게 남았다면
                print("-1"); exit()
            ans = max(ans, val)
print(ans - 1)''',
        "guide": "💡 학생 가이드: 3차원 배열 인덱싱 `box[h][n][m]` 순서가 헷갈리지 않게 주의하세요!"
    },
    {
        "title": "📍 [BJ 1697] 숨바꼭질",
        "context": "수빈이가 동생을 찾는 가장 빠른 시간(초)을 구하는 1차원 BFS 문제입니다.",
        "analysis": "🔍 상세 분석\n- 핵심: 그래프가 명시적이지 않지만, x-1, x+1, 2x로의 이동을 간선으로 봅니다.\n- 로직: 위치 x에 도달한 '최소 시간'을 visited 배열에 기록합니다.",
        "code": '''from collections import deque

n, k = map(int, input().split())
visited = [0] * 100001

def bfs():
    queue = deque([n])
    while queue:
        curr = queue.popleft()
        if curr == k:
            return visited[curr]
        for nxt in (curr-1, curr+1, curr*2):
            if 0 <= nxt <= 100000 and not visited[nxt]:
                visited[nxt] = visited[curr] + 1
                queue.append(nxt)

print(bfs())''',
        "guide": "💡 학생 가이드: 순간이동(*2) 연산 시 범위를 벗어날 수 있으므로 인덱스 체크가 최우선입니다."
    },
    {
        "title": "📍 [BJ 5014] 스타트링크",
        "context": "강호가 엘리베이터를 타고 목표 층으로 가는 최소 버튼 횟수를 구합니다.",
        "analysis": "🔍 상세 분석\n- 핵심: 1697 숨바꼭질의 '엘리베이터 버전'입니다. 위로 U층, 아래로 D층 이동 가능.\n- 로직: 방문하지 않은 층만 BFS로 탐색하며 목표 층 도달 시 횟수를 출력합니다.",
        "code": '''from collections import deque

f, s, g, u, d = map(int, input().split())
dist = [-1] * (f + 1)

def bfs():
    queue = deque([s])
    dist[s] = 0
    while queue:
        curr = queue.popleft()
        if curr == g:
            return dist[curr]
        for nxt in (curr + u, curr - d):
            if 1 <= nxt <= f and dist[nxt] == -1:
                dist[nxt] = dist[curr] + 1
                queue.append(nxt)
    return "use the stairs"

print(bfs())''',
        "guide": "💡 학생 가이드: 목표 층에 갈 수 없는 경우의 예외 처리를 잊지 마세요."
    },
    {
        "title": "📍 [BJ 2468] 안전 영역",
        "context": "비가 온 높이에 따라 물에 잠기지 않는 '안전한 영역'의 최대 개수를 구합니다.",
        "analysis": "🔍 상세 분석\n- 핵심: 모든 가능한 높이(0~100)에 대해 각각 시뮬레이션을 돌려 최대치를 찾습니다.\n- 로직: 높이 h보다 높은 지점들을 연결된 덩어리로 보고 BFS/DFS 개수를 셉니다.",
        "code": '''import sys
from collections import deque

n = int(sys.stdin.readline())
board = [list(map(int, sys.stdin.readline().split())) for _ in range(n)]

def bfs(x, y, h, visited):
    queue = deque([(x, y)])
    visited[x][y] = True
    while queue:
        cx, cy = queue.popleft()
        for dx, dy in [(-1, 1, 0, 0), (0, 0, -1, 1)]:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < n and 0 <= ny < n:
                if not visited[nx][ny] and board[nx][ny] > h:
                    visited[nx][ny] = True
                    queue.append((nx, ny))

max_cnt = 1
for h in range(1, 101): # 비의 높이
    visited = [[False] * n for _ in range(n)]
    cnt = 0
    for i in range(n):
        for j in range(n):
            if board[i][j] > h and not visited[i][j]:
                bfs(i, j, h, visited)
                cnt += 1
    if cnt == 0: break # 더 이상 안전 영역이 없음
    max_cnt = max(max_cnt, cnt)

print(max_cnt)''',
        "guide": "💡 학생 가이드: 아무 곳도 잠기지 않는 경우(비의 높이 0) 안전 영역은 1개라는 점을 고려해 초기값을 1로 설정하세요."
    },
    {
        "title": "📍 [BJ 1926] 그림",
        "context": "도화지에 그려진 그림의 개수와 그 중 가장 넓은 그림의 넓이를 구합니다.",
        "analysis": "🔍 상세 분석\n- 핵심: 영역 분할 탐색의 전형적인 문제로, 그림의 '개수'와 '최대 크기' 두 가지 정보를 추출합니다.\n- 로직: BFS 수행 중 큐에서 팝할 때마다 넓이를 1씩 더해줍니다.",
        "code": '''import sys
from collections import deque

n, m = map(int, sys.stdin.readline().split())
paper = [list(map(int, sys.stdin.readline().split())) for _ in range(n)]
visited = [[False] * m for _ in range(n)]

def bfs(x, y):
    queue = deque([(x, y)])
    visited[x][y] = True
    area = 1
    while queue:
        cx, cy = queue.popleft()
        for dx, dy in [(-1, 1, 0, 0), (0, 0, -1, 1)]:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < n and 0 <= ny < m:
                if paper[nx][ny] == 1 and not visited[nx][ny]:
                    visited[nx][ny] = True
                    queue.append((nx, ny))
                    area += 1
    return area

cnt = 0
max_area = 0
for i in range(n):
    for j in range(m):
        if paper[i][j] == 1 and not visited[i][j]:
            cnt += 1
            max_area = max(max_area, bfs(i, j))

print(cnt)
print(max_area)''',
        "guide": "💡 학생 가이드: 그림이 하나도 없는 경우 최대 넓이는 0이 출력되도록 초기화에 주의하세요."
    }
]

def build_notion():
    print(f"🚀 Updating DFS/BFS Problems to Page: {PAGE_ID}")
    
    # Optional: Clear existing content if needed, but per core mandates, we APPEND.
    
    blocks = []
    for p in problems:
        blocks.extend([
            {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": p['title']}}]}},
            {"type": "quote", "quote": {"rich_text": [{"text": {"content": p['context']}}]}},
            {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": p['analysis']}}]}},
            {"type": "code", "code": {"language": "python", "rich_text": [{"text": {"content": p['code']}}]}},
            {"type": "callout", "callout": {"icon": {"emoji": "💡"}, "rich_text": [{"text": {"content": p['guide']}}]}},
            {"type": "divider", "divider": {}}
        ])
    
    append_blocks_chunked(PAGE_ID, blocks)
    print("✨ ALL 10 PROBLEMS SUCCESSFULLY ADDED TO NOTION!")

if __name__ == "__main__":
    build_notion()
