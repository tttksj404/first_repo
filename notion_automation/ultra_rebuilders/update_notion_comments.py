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

# 📝 각 문제별 '주석이 보강된 정답 코드' (ASCII Log Safe)
commented_codes = {
    "1260": '''import sys
from collections import deque

# 1. 입력 처리 및 인접 리스트 구축
n, m, v = map(int, sys.stdin.readline().split())
graph = [[] for _ in range(n + 1)] # 1~N번 노드 관리
for _ in range(m):
    a, b = map(int, sys.stdin.readline().split())
    graph[a].append(b); graph[b].append(a) # 양방향 연결

# 2. 작은 번호부터 방문하기 위해 모든 인접 리스트 정렬
for i in range(1, n + 1): graph[i].sort()

# DFS: 스택/재귀 활용 (수직 탐색)
def dfs(c):
    visited_dfs[c] = True; print(c, end=' ')
    for n in graph[c]:
        if not visited_dfs[n]: dfs(n) # 방문 안했다면 더 깊이 탐색

# BFS: 큐 활용 (수평 탐색)
def bfs(s):
    q = deque([s]); visited_bfs[s] = True
    while q:
        c = q.popleft(); print(c, end=' ')
        for n in graph[c]:
            if not visited_bfs[n]:
                visited_bfs[n] = True; q.append(n) # 넣을 때 방문 체크가 국룰

visited_dfs = [False]*(n+1); visited_bfs = [False]*(n+1)
dfs(v); print(); bfs(v)''',

    "2178": '''from collections import deque
# 최단 거리는 무조건 BFS! (가중치 1인 격자판)
n, m = map(int, input().split())
maze = [list(map(int, input())) for _ in range(n)]

def bfs():
    q = deque([(0, 0)]) # 시작점 (0,0)
    dx, dy = [-1, 1, 0, 0], [0, 0, -1, 1] # 상하좌우 방향
    while q:
        cx, cy = q.popleft()
        for i in range(4):
            nx, ny = cx + dx[i], cy + dy[i]
            # 범위를 넘지 않고, 길(1)인 경우만 탐색
            if 0 <= nx < n and 0 <= ny < m and maze[nx][ny] == 1:
                maze[nx][ny] = maze[cx][cy] + 1 # 이전 칸 거리에 +1 (누적)
                q.append((nx, ny))
    return maze[n-1][m-1] # 마지막 칸까지의 누적 거리 반환

print(bfs())''',

    "2606": '''# 1번 컴퓨터와 연결된 모든 노드의 수 (컴포넌트 크기) 구하기
n = int(input()); m = int(input())
graph = [[] for _ in range(n+1)]
for _ in range(m):
    a, b = map(int, input().split())
    graph[a].append(b); graph[b].append(a)

visited = [False] * (n + 1); count = 0

def dfs(v):
    global count
    visited[v] = True
    for next_v in graph[v]:
        if not visited[next_v]:
            count += 1 # 새로 방문하는 컴퓨터 발견 시 카운트
            dfs(next_v)

dfs(1)
print(count)''',

    "2667": '''# 전체 지도를 훑으며 단지를 발견하면 그 단지의 집 개수 세기
def dfs(x, y):
    global cnt
    visited[x][y] = True; cnt += 1
    for dx, dy in [(-1, 1, 0, 0), (0, 0, -1, 1)]:
        nx, ny = x + dx, y + dy
        if 0 <= nx < n and 0 <= ny < n:
            if board[nx][ny] == 1 and not visited[nx][ny]:
                dfs(nx, ny)

n = int(input())
board = [list(map(int, input())) for _ in range(n)]
visited = [[False] * n for _ in range(n)]; results = []

for i in range(n):
    for j in range(n):
        # 아직 방문 안 한 집(1)을 만나면 새로운 단지 탐색 시작
        if board[i][j] == 1 and not visited[i][j]:
            cnt = 0; dfs(i, j)
            results.append(cnt)

results.sort() # 집의 수 기준 오름차순 정렬
print(len(results))
for r in results: print(r)''',

    "2644": '''# 두 사람의 촌수 = 그래프 상의 최단 경로 길이
n = int(input()); a, b = map(int, input().split()); m = int(input())
graph = [[] for _ in range(n+1)]
for _ in range(m):
    p, c = map(int, input().split())
    graph[p].append(c); graph[c].append(p) # 부모-자식 양방향

res = -1
def dfs(curr, target, chon):
    global res
    visited[curr] = True
    if curr == target: # 목표 인물 도달 시 촌수 저장
        res = chon; return
    for next_v in graph[curr]:
        if not visited[next_v]:
            dfs(next_v, target, chon + 1) # 깊이(촌수) 1씩 늘리며 탐색

visited = [False] * (n + 1)
dfs(a, b, 0)
print(res)''',

    "7569": '''import sys
from collections import deque
# 3차원 토마토 (멀티소스 BFS)
m, n, h = map(int, sys.stdin.readline().split())
box = []; q = deque()

for i in range(h):
    layer = []
    for j in range(n):
        row = list(map(int, sys.stdin.readline().split()))
        for k in range(m):
            if row[k] == 1: q.append((i, j, k)) # 익은 토마토 모두 큐에 삽입
        layer.append(row)
    box.append(layer)

# 6방향 탐색: 위, 아래, 상, 하, 좌, 우
dh, dn, dm = [1, -1, 0, 0, 0, 0], [0, 0, -1, 1, 0, 0], [0, 0, 0, 0, -1, 1]

while q:
    ch, cn, cm = q.popleft()
    for i in range(6):
        nh, nn, nm = ch + dh[i], cn + dn[i], cm + dm[i]
        if 0 <= nh < h and 0 <= nn < n and 0 <= nm < m:
            if box[nh][nn][nm] == 0: # 안 익은 토마토 발견
                box[nh][nn][nm] = box[ch][cn][cm] + 1 # 일수 기록
                q.append((nh, nn, nm))

ans = 0
for layer in box:
    for row in layer:
        for val in row:
            if val == 0: print("-1"); exit() # 하나라도 안 익었으면 실패
            ans = max(ans, val)
print(ans - 1) # 시작값이 1이었으므로 1 보정''',

    "1697": '''from collections import deque
# 1차원 공간에서의 최소 시간 (BFS)
n, k = map(int, input().split())
visited = [0] * 100001

def bfs():
    q = deque([n])
    while q:
        c = q.popleft()
        if c == k: return visited[c] # 동생 위치 도달 시 시간 반환
        for nxt in (c-1, c+1, c*2): # 세 가지 이동 경로
            if 0 <= nxt <= 100000 and not visited[nxt]:
                visited[nxt] = visited[c] + 1 # 도달 시간 기록
                q.append(nxt)

print(bfs())''',

    "5014": '''from collections import deque
# 엘리베이터 이동 (1차원 BFS)
f, s, g, u, d = map(int, input().split())
dist = [-1] * (f + 1)

def bfs():
    q = deque([s]); dist[s] = 0
    while q:
        c = q.popleft()
        if c == g: return dist[c] # 목표 층 도착
        for nxt in (c + u, c - d): # 위로 U층, 아래로 D층
            if 1 <= nxt <= f and dist[nxt] == -1:
                dist[nxt] = dist[c] + 1
                q.append(nxt)
    return "use the stairs" # 도달 불가능한 경우

print(bfs())''',

    "2468": '''import sys
from collections import deque
# 비의 높이 h에 따라 물에 잠기지 않는 영역 개수 구하기
n = int(sys.stdin.readline())
board = [list(map(int, sys.stdin.readline().split())) for _ in range(n)]

def bfs(x, y, h, v):
    q = deque([(x, y)]); v[x][y] = True
    while q:
        cx, cy = q.popleft()
        for dx, dy in [(-1, 1, 0, 0), (0, 0, -1, 1)]:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < n and 0 <= ny < n:
                # 높이가 h보다 높고 방문 안 한 곳 탐색
                if not v[nx][ny] and board[nx][ny] > h:
                    v[nx][ny] = True; q.append((nx, ny))

max_cnt = 1 # 비가 아예 안 올 경우(h=0) 영역은 1개
for h in range(1, 101):
    v = [[False] * n for _ in range(n)]; cnt = 0
    for i in range(n):
        for j in range(n):
            if board[i][j] > h and not v[i][j]:
                bfs(i, j, h, v); cnt += 1
    if cnt == 0: break # 더 이상 안전 영역이 없으면 종료
    max_cnt = max(max_cnt, cnt)
print(max_cnt)''',

    "1926": '''import sys
from collections import deque
# 그림의 개수와 가장 넓은 그림의 넓이 구하기
n, m = map(int, sys.stdin.readline().split())
paper = [list(map(int, sys.stdin.readline().split())) for _ in range(n)]
v = [[False] * m for _ in range(n)]

def bfs(x, y):
    q = deque([(x, y)]); v[x][y] = True; area = 1
    while q:
        cx, cy = q.popleft()
        for dx, dy in [(-1, 1, 0, 0), (0, 0, -1, 1)]:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < n and 0 <= ny < m:
                if paper[nx][ny] == 1 and not v[nx][ny]:
                    v[nx][ny] = True; q.append((nx, ny)); area += 1
    return area

cnt = 0; max_area = 0
for i in range(n):
    for j in range(m):
        if paper[i][j] == 1 and not v[i][j]:
            cnt += 1; max_area = max(max_area, bfs(i, j))
print(cnt); print(max_area)'''
}

def update():
    print("--- Fetching blocks from Notion ---")
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    res = requests.get(url, headers=HEADERS)
    blocks = res.json().get('results', [])
    
    current_num = None
    count = 0
    
    for b in blocks:
        if b['type'] == 'heading_2':
            txt = b['heading_2']['rich_text'][0]['plain_text']
            for num in commented_codes.keys():
                if num in txt:
                    current_num = num
                    break
        
        if b['type'] == 'code' and current_num:
            block_id = b['id']
            new_code = commented_codes[current_num]
            requests.patch(f"https://api.notion.com/v1/blocks/{block_id}", headers=HEADERS, json={
                "code": {"rich_text": [{"type": "text", "text": {"content": new_code}}]}
            })
            print(f"SUCCESS: Updated comments for BJ {current_num}")
            count += 1
            current_num = None
            time.sleep(0.5)
    print(f"DONE: Total {count} blocks updated.")

if __name__ == "__main__":
    update()
