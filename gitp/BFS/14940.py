'''
dfs로 visited 쓰고 가지치기 일단 거리출력이니까 거리 +1씩 해줘야함 
1. not visited 면 백트레킹 돌아오기 가지치기 return
2. 기저조건 다음 위치가 2가 되면 끝남 거기서 return
3. 


'''
from collections import deque


def bfs(si,sj):
    queue=deque([(si,sj)]) #queue에 처음 넣어줄떈 ([])이렇게 묶어주는게 필요함 
    visited[si][sj]=0

    while queue:
        i,j = queue.popleft()

        for a in range(4):
            nr=i+dr[a]
            nc=j+dc[a]

            if 0 <= nr < n and 0 <= nc < m and visited[nr][nc] == -1:
                if dist[nr][nc] == 1:
                    visited[nr][nc]=visited[i][j]+1
                    queue.append((nr,nc))
    
    
    



dr=[-1,1,0,0]
dc=[0,0,-1,1]
n,m = map(int,input().split()) #n은 세로 m은 가로 
dist = [list(map(int,input().split())) for _ in range(n)]

visited=[[-1]*m for _ in range(n)]

start_i, start_j = -1,-1 #처음에 절대 갈 수 없는 -1,-1로 구현 일종의 플래그 역할 도달할 수 없는 위치 -1 
#2에서 출발해서 거꾸로 각 지점의 거리를 더해서 반대로 구해주기 
for i in range(n):
    for j in range(m):
        if dist[i][j]==2:
            start_i, start_j = i,j

        elif dist[i][j]==0:
            visited[i][j]=0
            
bfs(start_i,start_j)

for row in visited:
        print(*(row))




