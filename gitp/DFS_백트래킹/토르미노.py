import sys
input = sys.stdin.readline

# N: 세로, M: 가로
n, m = map(int, input().split())
grid = [list(map(int, input().split())) for _ in range(n)]
visited = [[False] * m for _ in range(n)] # 방문 체크용
ans = 0

# 상하좌우 이동
dx = [-1, 1, 0, 0]
dy = [0, 0, -1, 1]

def dfs(x, y, depth, total_sum):
    global ans
    
    # [종료 조건] 블럭 3개를 다 골랐다면 최댓값 갱신
    if depth == 3:
        ans = max(ans, total_sum)
        return

    # 상하좌우 탐색
    for i in range(4):
        nx, ny = x + dx[i], y + dy[i]
        
        # 격자 범위 내에 있고, 아직 방문하지 않았다면
        if 0 <= nx < n and 0 <= ny < m and not visited[nx][ny]:
            visited[nx][ny] = True
            # 깊이를 1 늘리고, 합계에 값을 더해서 재귀 호출
            dfs(nx, ny, depth + 1, total_sum + grid[nx][ny])
            visited[nx][ny] = False # (백트래킹) 나와서는 방문 표시 해제

# 모든 칸을 시작점으로 두고 DFS 돌리기
for i in range(n):
    for j in range(m):
        visited[i][j] = True
        dfs(i, j, 1, grid[i][j]) # depth 1부터 시작
        visited[i][j] = False

print(ans)