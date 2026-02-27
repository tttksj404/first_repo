from collections import deque
N,M= map(int,input().split())
canvas = [list(map(int,input().split())) for _ in range(N)]
visited = [[False]*M for _ in range(N)]
s_i,s_j=0,0
max_widith=0
drawing_count=0
queue=deque()

dr=[-1,1,0,0]
dc=[0,0,-1,1]

def bfs(i_i,j_j):
    global each_widith
    global  drawing_count
    global  max_widith
    each_widith=1
    while queue:
        i_i,j_j=queue.popleft()

        for a in range(4):
            nr=i_i+dr[a]
            nc=j_j+dc[a]

            if 0<=nr<N and 0<=nc<M and visited[nr][nc]==False and canvas[nr][nc]==1:
                visited[nr][nc]=True
                each_widith+=1
                queue.append((nr,nc))
    drawing_count+=1
    if each_widith>max_widith:
        max_widith=each_widith

    return



for i in range(N):
    for j in range(M):
        if canvas[i][j]==1 and visited[i][j]==False:
            s_i,s_j=i,j
            queue.append((s_i,s_j))
            visited[i][j]=True
            bfs(s_i,s_j)
print(drawing_count)
print(max_widith)