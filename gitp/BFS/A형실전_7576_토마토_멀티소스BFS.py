# 자주 틀리는 포인트
# 1) 시작점(익은 토마토) 전부를 queue에 먼저 넣어야 멀티소스 BFS 성립
# 2) box[nr][nc]=box[r][c]+1 갱신 안 하면 날짜 계산이 깨짐
# 3) 마지막에 0 남아있는지 반드시 검사하고 있으면 -1 출력
import sys
from collections import deque

# BOJ 7576 토마토 (2차원)
# 멀티소스 BFS로 최소 날짜 계산

input = sys.stdin.readline
M, N = map(int, input().split())
box = [list(map(int, input().split())) for _ in range(N)]

q = deque()
for r in range(N):
    for c in range(M):
        if box[r][c] == 1:
            q.append((r, c))

dr = [-1, 1, 0, 0]
dc = [0, 0, -1, 1]

while q:
    r, c = q.popleft()

    for k in range(4):
        nr = r + dr[k]
        nc = c + dc[k]

        if nr < 0 or nr >= N or nc < 0 or nc >= M:
            continue
        if box[nr][nc] != 0:
            continue

        box[nr][nc] = box[r][c] + 1
        q.append((nr, nc))

ans = 0
for row in box:
    for v in row:
        if v == 0:
            print(-1)
            sys.exit(0)
    ans = max(ans, max(row))

print(ans - 1)

