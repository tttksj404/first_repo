'''
이동할때 시간은 거리를 나타냄 그냥 거리+1 씩 해주면됨 queue 어펜드 해줄때 마다 +1 씩 해주기 
나중에 최소날짜가 그 거리가됨 
'''
from collections import deque


def bfs():
    global depth
    while queue:
        i,j=queue.popleft()

        for a in range(4):
            nr=i+dr[a]
            nc=j+dc[a]
        
            if 0<=nr<N and 0<=nc<M:
                if visited[nr][nc]==False and box[nr][nc]==0: #이미 0인것만 탐색하는거라 visited가 딱히 필요없음 
                    visited[nr][nc]=True
                    box[nr][nc]=box[i][j]+1 #반드시 동시탐색이니 거리계산할땐 bfs는 nrnc를 이전값에다가 1더한걸로 덮어씌어줘야한다
                    # 만약 10개의 토마토가 첫날 동시에 익어도 depth+=1하면 10이되버림 실제로는 1이 나와야하는데  
                    queue.append((nr,nc))
                if box[nr][nc]==-1 and visited[nr][nc]==False:
                    visited[nr][nc]=True




dr=[-1,1,0,0]
dc=[0,0,-1,1]
queue=deque()
M,N = map(int,input().split()) #M 가로 / N세로 
box = [list(map(int, input().split())) for _ in range(N)]
visited= [[False]*M for _ in range(N)]
depth=-1
si,sj=0,0
for i in range(N):
    for j in range(M):
        if box[i][j]==1 and visited[i][j]==False:
            visited[i][j]=True
            si,sj=i,j
            queue.append((si,sj))
bfs()#어짜피 여기서 해도 상관없는게 시작점에 1이 들어간 시작점은 맵당 하나밖에 없어서 

ans = 0 #이런식으로 행과 열을 바로 불러올 수 있는 변수가 존재함
for row in box:
    for cell in row:
        if cell ==0: #행과 열의 값이 0이면 bfs끝났는데 탐색안된곳 있으니까 -1나와야함
            print(-1)
            exit() #이거하면 여기서 모든걸 끝냄 그냥 print도 안하게됨 알아놓기 치명적오류나 답이나오면 행함 
        ans = max(ans,cell) #지금 값중에 가장 큰게 그만큼의 시간을 뜻하기에 max값 불러옴 


print(ans-1) #저장될때 부터 토마토가 익었으면 1이므로 그걸 빼서 0으로 표시 문제 조건맞추기 


