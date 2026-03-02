from collections import deque
N=int(input())
square = [list(map(int,input().strip())) for _ in range(N)]
visited = [[False]*N for _ in range(N)]
queue=deque()
s_i,s_j=0,0
dr=[-1,1,0,0]
dc=[0,0,-1,1]
town=[]
house=0


def bfs(i,j):
    global town
    global house
    
    house=1
    while queue:
        i,j=queue.popleft()
        for a in range(4):
            nr = i+dr[a]
            nc = j+dc[a]

            if 0<=nr<N and 0<=nc<N and visited[nr][nc]==False and square[nr][nc]==1:
                visited[nr][nc]=True
                queue.append((nr,nc))
                house+=1
    town.append(house)
    return

for i in range(N):
    for j in range(N):
        if square[i][j]==1 and visited[i][j]==False:
            s_i,s_j=i,j
            visited[i][j]=True
            queue.append((s_i,s_j))
            bfs(s_i,s_j)

town.sort()
print(len(town))
for ans in town:
    print(ans)


