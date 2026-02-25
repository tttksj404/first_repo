'''
연결된 토마토가 전부 익을때 까지의 일자 더해주기 그 일자 출력
아까처럼 result= -1로 디폴트 값 주기
start,end에서 첫판의 end 값이 다음 판의 start가 됨 이거 조건도 dfs에 주면된다
visited를 한판 돌릴때 마다 초기화 필요 
그리고 안익은 토마토인 0이 1로 바뀌는 것도 생각필요 -1은 안거침 

이런 bfs문제임 !!!최소 시간!!
'''
import sys
from collections import deque

M,N,H = map(int,sys.stdin.readline().split()) #M은 가로 /N은 세로 / H는 높이
box = [] #한층씩 아파트 채울때 그 층 정보 담을 공간
queue = deque()

for h in range(H):
    layer=[] #한층의 전체 정보임을 나타냄 
    for n in range(N):
        row = list(map(int,sys.stdin.readline().split()))
        for m in range(M):
            if row[m]==1:
                # 익은 토마토를 발견하면 (층, 세로, 가로) 위치를 큐에 저장
                queue.append((h,n,m))
        layer.append(row)
    box.append(layer) #층별 정보를 box에 담음

#위, 아래, 상, 하 , 좌, 우
dh=[1,-1,0,0,0,0]
dn=[0,0,-1,1,0,0]
dm=[0,0,0,0,-1,1]

while queue:
    h,n,m = queue.popleft() #지금 탐색하려는 최우선순위 값 갱신 해주는거 반드시 필요

    for i in range(6):
        nh,nn,nm = h+dh[i], n+dn[i], m+dm[i]

        if 0<=nh<H and 0<=nn<N and 0<=nm<M:
            if box[nh][nn][nm]==0:
                box[nh][nn][nm]=box[h][n][m]+1 #bfs는 끝까지 간 시간을 구하니까 갈때마다 1씩 시간 더해주는거
                queue.append((nh,nn,nm)) #다음 탐색값 큐에 후순위로 넣기 

ans =0
for layer in box:
    for row in layer:
        for meat in row:
            if meat ==0:
                print("-1")
                exit()
        ans= max(ans,max(row))

print(ans-1) #시작점이 1이였으니까 익어있는 토마토가 1이였으므로 일차로 계산하면 0일차에 1 그래서 이값 보정 

            
