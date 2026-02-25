'''
멀티소스 BFS
- 시작점이 여러 개인 경우(불, 바이러스, 익은 토마토 등)
- queue에 시작점들을 먼저 다 넣고 시작
- dist 배열로 최단 시간/거리 관리
'''

from collections import deque

# 0: 빈칸, 1: 벽, 2: 시작점(여러개)
grid = [
    [0, 0, 0, 1, 2],
    [1, 1, 0, 1, 0],
    [2, 0, 0, 0, 0],
    [0, 1, 1, 0, 0],
]

N = len(grid)
M = len(grid[0])

dist = [[-1] * M for _ in range(N)]
q = deque()

for r in range(N):
    for c in range(M):
        if grid[r][c] == 2:
            q.append((r, c))
            dist[r][c] = 0

dr = [-1, 1, 0, 0]
dc = [0, 0, -1, 1]

while q:
    r, c = q.popleft()

    for k in range(4):
        nr = r + dr[k]
        nc = c + dc[k]

        if nr < 0 or nr >= N or nc < 0 or nc >= M:
            continue
        if grid[nr][nc] == 1:
            continue
        if dist[nr][nc] != -1:
            continue

        dist[nr][nc] = dist[r][c] + 1
        q.append((nr, nc))

print('[최단거리 맵]')
for row in dist:
    print(row)
