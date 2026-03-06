from collections import deque


def bfs(i, j):
    if yard[i][j]=="o":
        sheep=1
        wolf=0
    else:
        sheep=0
        wolf=1
    
    global survive_sheep
    global survive_wolf

    while queue:
        i, j = queue.popleft()

        for a in range(4):
            nr = i + dr[a]
            nc = j + dc[a]

            if 0 <= nr < R and 0 <= nc < C and visited[nr][nc] == False and yard[nr][nc] != "#":
                # [문제점 1] '.'(빈칸)일 때 visited 처리와 queue.append를 하지 않아서
                # 같은 구역 탐색이 중간에 끊길 수 있음.
                if yard[nr][nc] == "v":
                    wolf += 1
                    visited[nr][nc] = True
                    queue.append((nr, nc))

                elif yard[nr][nc] == "o":
                    sheep += 1
                    visited[nr][nc] = True
                    queue.append((nr, nc))
                elif yard[nr][nc] ==".":
                    visited[nr][nc]=True
                    queue.append((nr,nc))
                    

    # [문제점 2] 시작 좌표(i, j)가 o/v여도 sheep/wolf에 처음 1을 더하지 않아
    # 시작 칸 동물 카운트가 누락됨.
    if wolf < sheep:
        survive_sheep += sheep
    else:
        survive_wolf += wolf

    # [문제점 3] 채점 환경(BOJ)에서는 중간 print가 있으면 출력 형식이 깨져 오답 가능.
    

    return


R, C = map(int, input().split())  # R은 행 C는 열
yard = [list(map(str, input().strip())) for _ in range(R)]
survive_sheep = 0
survive_wolf = 0
sr, sc = 0, 0
dr = [-1, 1, 0, 0]
dc = [0, 0, -1, 1]
queue = deque()

visited = [[False] * C for _ in range(R)]
for r in range(R):
    for c in range(C):
        if yard[r][c] == "o" and visited[r][c] == False:
            sr, sc = r, c
            visited[r][c] = True
            queue.append((sr, sc))
            bfs(sr, sc)

        if yard[r][c] == "v" and visited[r][c] == False:
            sr, sc = r, c
            visited[r][c] = True
            queue.append((sr, sc))
            bfs(sr, sc)
print(survive_sheep, survive_wolf)

# [문제점 4] 정답 제출용 최종 출력이 없음.
# 정답 형식은 보통: print(survive_sheep, survive_wolf)
