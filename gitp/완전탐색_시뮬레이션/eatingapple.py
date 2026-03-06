'''
사과먹기로 달팽이처럼 우회전 밖에 안되서 안쪽으로 밖에 돌아야함 
초반에는 상하좌우에서 상이 안됨 

먼저 타겟은 1,2,3 순서이고 타겟을 모아놓는 곳에 1,2,3의 위치정보 넣어두기 차례대로 꺼내서 쓰기


이거 방향을 설정해줘야함 가는 쪽에서 우측 좌측이 어디인지 
처음엔 상하좌우에서 1. 우가 직선 하가 우측  / 우측으로 돌면 그때 부턴 2. 하가 직선 좌가 우측 / 3. 좌가 직선 상이 우측 /4. 상이 직선 우가 우측 
5. 부터는 1반복 
-> 우하좌상 반복 
출발점에서 1까지 가기 위해서 

그냥 완전탐색 해서 dfs로 min 구하기
백트레킹으로 방향 달라질때는 복구해서 다시갈 수 있게 한 방향일때는 백트레킹으로 고정

# matrix[현재방향][사분면]
    # 방향: 0:우, 1:하, 2:좌, 3:상
    # 사분면: 0:UR, 1:DR, 2:DL, 3:UL
turn_matrix = [
    [3, 1, 2, 3], # 현재 우(0)
    [3, 3, 1, 2], # 현재 하(1)
    [2, 3, 3, 1], # 현재 좌(2)
    [1, 2, 3, 3]  # 현재 상(3)
]

T= int(input())
for tc in range(1,T+1):
    N=int(input())
    game= [list(map(int,input().split())) for _ in range(N)]
    #우하좌상인데 가상의 메트릭스 만들어서 현재 위치에서 1,2,3,4사분면 
    # 우측이 직선일때 먼저 1사분면은 3번 돌아야함 , 2사분면은 4번 돌아야함 , 3사분면은 1번 ,4사분면은 2번 
    # 하측이 직선일때 1사분면 2번 2사분면 3번 / 3사분면 4번 / 4사분면 1번 
    # 좌측이 직선일때 1사분면 1번 2사분면 2번 / 3사분면 3번 / 4사분면 4번
    # 상측이 직선일때 1사분면 4번 2사분면 1번 / 3사분면 2번 / 4사분면 3번 

    
    
    target={}
    max_target=0
    for i in range(N):
        for j in range(N):
            if game[i][j]>0:
                target[game[i][j]]=(i,j) #첫번째 부터 불러올 수 있도록 딕셔너리로 저장
                max_target= max(max_target,game[i][j])

    current_r, current_c= 0,0
    current_dir=0
    ans=0

    for a in range(1, max_target+1):
        tr,tc=target[a]
        #위 매트릭스에서 2->3->4->1사분면 순서로  되어있어서 맞춰줘야함 
        if tr< current_r and current_c<tc:
            q_idx = 0 #2사분면의 경우
        elif tr>current_r and current_c<tc:
            q_idx =1 #3사분면의 경우
        elif tr>current_r and current_c>tc:
            q_idx =2 #4사분면의 경우
        elif tr<current_r and current_c>tc:
            q_idx=3 #1사분면의 경우 

        turns = turn_matrix[current_dir][q_idx]
        ans +=turns

        current_r,current_c=tr,tc
        current_dir=(current_dir+turns)%4 #지금은 0 즉 우측에서 시작인데 우회전 횟수만큼 우하좌상중 방향이 결정된다 

    print(f"#{tc} {ans}")

'''
from collections import deque

INF = 10**9

def solve_case(N, grid):

    # -----------------------------
    # 1. 맵에서 가장 큰 숫자를 찾아 사과 개수 M을 구한다.
    # 입력에서 M이 직접 주어지지 않기 때문
    # -----------------------------
    M = 0
    for i in range(N):
        for j in range(N):
            if grid[i][j] > M:
                M = grid[i][j]

    # -----------------------------
    # 2. dist 배열
    #
    # dist[x][y][dir][next]
    #
    # x, y   : 현재 위치
    # dir    : 현재 방향
    #          0 = 동, 1 = 남, 2 = 서, 3 = 북
    # next   : 다음에 먹어야 하는 사과 번호
    #
    # 값 : 해당 상태에 도달하기 위한 최소 우회전 횟수
    # -----------------------------
    dist = [[[[INF]*(M+2) for _ in range(4)] for _ in range(N)] for _ in range(N)]

    # -----------------------------
    # 3. 0-1 BFS를 위한 deque
    # -----------------------------
    dq = deque()

    # 시작 상태
    # (0,0) 위치에서 시작
    # 처음 방향은 오른쪽(동쪽)
    # 먹어야 할 첫 사과는 1번
    dist[0][0][0][1] = 0
    dq.append((0,0,0,1))

    # 방향 이동 벡터
    dx = [0,1,0,-1]   # 동 남 서 북
    dy = [1,0,-1,0]

    # -----------------------------
    # 4. 0-1 BFS 시작
    #
    # 전진 비용 = 0
    # 우회전 비용 = 1
    #
    # 비용이 0이면 appendleft
    # 비용이 1이면 append
    # -----------------------------
    while dq:
        x,y,d,nxt = dq.popleft()

        # 현재 상태까지의 우회전 횟수
        cur = dist[x][y][d][nxt]

        # -----------------------------
        # (1) 우회전
        #
        # 방향만 바뀌고 위치는 그대로
        # 비용 = 1
        # -----------------------------
        nd = (d+1)%4

        if dist[x][y][nd][nxt] > cur+1:
            dist[x][y][nd][nxt] = cur+1
            dq.append((x,y,nd,nxt))

        # -----------------------------
        # (2) 전진
        #
        # 현재 방향으로 한 칸 이동
        # 비용 = 0
        # -----------------------------
        nx = x + dx[d]
        ny = y + dy[d]

        # 맵 범위 안인지 확인
        if 0<=nx<N and 0<=ny<N:

            # 기본적으로 다음 사과 번호는 그대로
            nnxt = nxt

            # 만약 현재 칸이 먹어야 할 사과라면
            # 사과를 먹고 다음 번호로 넘어간다
            if nxt<=M and grid[nx][ny] == nxt:
                nnxt = nxt+1

            # 비용 0 이동이므로 appendleft 사용
            if dist[nx][ny][d][nnxt] > cur:
                dist[nx][ny][d][nnxt] = cur
                dq.appendleft((nx,ny,d,nnxt))

    # -----------------------------
    # 5. 모든 사과를 먹은 상태 찾기
    #
    # next == M+1 이면
    # 마지막 사과까지 모두 먹은 상태
    # -----------------------------
    ans = INF
    target = M+1

    for i in range(N):
        for j in range(N):
            for d in range(4):
                ans = min(ans, dist[i][j][d][target])

    return ans


# -----------------------------
# 메인 실행
# -----------------------------
T = int(input())

for tc in range(1, T+1):

    # 맵 크기
    N = int(input())

    # 맵 입력
    grid = [list(map(int,input().split())) for _ in range(N)]

    # 최소 우회전 횟수 계산
    result = solve_case(N, grid)

    # 출력 형식
    print(f"#{tc} {result}")
    


    




