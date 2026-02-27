from collections import deque 
import sys
input= sys.stdin.readline


def bfs():
    N,M = map(int,input().split())
    maze = [list(map(int,input().strip())) for _ in range(N)]

    dist = [[0]*M for _ in range(N)]
    dr= [-1,1,0,0]
    dc=[0,0,-1,1]

    queue = deque([(0,0)]) #queue를 써야지 시작점으로 부터 근거리있는 것부터 first in first out으로 처리하기에

    #만약 스택이면 가장 나중 last in first out이기에 4방 탐색에서 한쪽에 있는 부분만 먼저 갔다가 계속 그렇게 나아가서 
    #목표 찍고 돌아오게된다 
    dist[0][0]=1

    while queue:
        r,c=queue.popleft() 

        if r==N-1 and c==M-1: #bfs로 목표를 찍고 돌아올 경우
            return dist[r][c]
        
        for a in range(4):
            nr = r+dr[a]
            nc= c+dc[a]
            #문제의 조건 부분은 델타탐색의 조건에서 추가로 더 해주면된다
            if 0<=nr<N and 0<=nc<M and maze[nr][nc]==1 and dist[nr][nc]==0:
                dist[nr][nc]=dist[r][c]+1
                queue.append((nr,nc))
    return -1 #실제로는 작동하지 않지만 길이없는 예외상황을 설명하기 위한 안전장치임 

print(bfs())
