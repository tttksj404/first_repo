'''
이건 높이에 따라서 범위가 결정되는데 그렇게 결정된 범위에 따라서 몇개의 조각이 나오는지 판단하고 높이를 갱신하주면된다
최대조각을 찾아서 
높이가 바뀌면 높이에 따라 배열을 자동으로 바꿔주고 bfs 탐색해서 조각 개수 찾기 

최대 조각이 나오는 높이를 찾아야함 
'''
from collections import deque

def bfs(i_i,j_j):
    global count
    while queue:
        i_i,j_j=queue.popleft() #큐에서 처음 가져오는 값 설정
        dr=[-1,1,0,0]
        dc=[0,0,-1,1]

        for a in range(4):
            nr=i_i+dr[a]
            nc=j_j+dc[a]

            if 0<=nr<N and 0<=nc<N and area[nr][nc]>length and visited[nr][nc]==False: #조건식 추가 
                visited[nr][nc]=True
                queue.append((nr,nc))
    count+=1
    return






N=int(input())
area = [list(map(int,input().split())) for _ in range(N)]
s_i,s_j=0,0
max_pieces=1
queue=deque()
#높이정해주기 / 근데 높이가 결정되었을때 area가 전부 잠기면 그냥 break하고 최대값만 출력
for length in range(1,101):
    count=0
    visited = [[False] * N for _ in range(N)] #높이마다 방문 기록 초기화 해서 최대 안전지대 구하기 
    for i in range(N):
        for j in range(N):
            if area[i][j]>length and visited[i][j]!=True:
                visited[i][j]=True
                s_i,s_j=i,j
                queue.append((s_i,s_j))
                bfs(s_i,s_j)
    if count==0:
        break
    if count>max_pieces:
        max_pieces=count
print(max_pieces)







