'''

1번 블록-> 위에서 아래면 우측으로 / 우측에서 좌측이면 상 
2번 블록-> 하에서 상 이면 우 / 우에서 좌면 하 
3번 블록-> 하에서 상이면 좌 / 좌에서 우면 하 
4번 블록-> 좌에서 우면 상 / 상에서 하면 좌 
5번 블록-> 전부다 되돌아감 

걲여지는거 빼고는 전부 원래 방향으로 방향만 바꿔서 되돌아가는데 
혹여나 출발점으로 돌아오면 끝 혹은 블랙홀로 들어가면 끝

가장 많이 부딫치는 값을 찾아야하므로 dfs로 끝까지 전부다 돌아보고 max값 갱신 

nr,nc의 값이 원래 출발점보다 어떻느냐에 따라서 좌우냐 우좌냐 상하냐 하상이냐를 알 수 있음 이걸 조건으로 각 블록 보면됨 그리고 백트레킹으로 다시 
출발점으로 원복 

가는 와중에 블랙홀 만나면 그냥 break

웜홀 함수 정의해주기

1. 튕기는 블록 함수 정의
2. 웜홀 함수 정의
3. 나머진 일반 dfs 

'''
'''
def ordinary_wall(i,j):
    global bouns
    for a in range(4):
        nr=i+dr[a]
        nc=j+dc[a]

        if 0<=nr<N and 0<=nc<N and visited[nr][nc]==False:
            visited[nr][nc]=True
            if game[nr][nc]==1 and i<nr and j==nc: #1번 블록 상하->우 
                 bouns+=1
                 right(nr,nc)
            if game[nr][nc]==1 and i==nr and nc<j: #1번 블록 우좌->상
                 bouns+=1
                 up(nr,nc)
            if game[nr][nc]==2 and i>nr and nc==j: #2번 블록 하상->우
                 bouns+=1
                 right(nr,nc)
            if game[nr][nc]==2 and i==nr and j>nc: #2번 블록 우좌->하
                 bouns+=1
                 down(nr,nc)
            if game[nr][nc]==3 and i>nr and nc==j:
                 bouns+=1
                 left(nr,nc)
            if game[nr][nc]==3 and i==nr and nc>j:
                 bouns+=1
                 down(nr,nc)
            if game[nr][nc]==4 and i==nr and nc>j:
                 bouns+=1
                 up(nr,nc)
            if game[nr][nc]==4 and i>nr and nc==j:
                 bouns+=1
                 left(nr,nc)
            if game[nr][nc]==0:
                 ordinary_wall[nr][nc]
            if game[nr][nc]>=6:
                 ordinary_wall(wormholl(nr,nc))
            else:
                 return

def left(i,j):
    global bouns
    nr=i
    nc=j+dc[2]

    if 0<=nr<N and 0<=nc<N and visited[nr][nc]==False:
            visited[nr][nc]=True
            if game[nr][nc]==1 and i<nr and j==nc: #1번 블록 상하->우 
                 bouns+=1
                 right(nr,nc)
            if game[nr][nc]==1 and i==nr and nc<j: #1번 블록 우좌->상
                 bouns+=1
                 up(nr,nc)
            if game[nr][nc]==2 and i>nr and nc==j: #2번 블록 하상->우
                 bouns+=1
                 right(nr,nc)
            if game[nr][nc]==2 and i==nr and j>nc: #2번 블록 우좌->하
                 bouns+=1
                 down(nr,nc)
            if game[nr][nc]==3 and i>nr and nc==j:
                 bouns+=1
                 left(nr,nc)
            if game[nr][nc]==3 and i==nr and nc>j:
                 bouns+=1
                 down(nr,nc)
            if game[nr][nc]==4 and i==nr and nc>j:
                 bouns+=1
                 up(nr,nc)
            if game[nr][nc]==4 and i>nr and nc==j:
                 bouns+=1
                 left(nr,nc)
            if game[nr][nc]==0:
                 left[nr][nc]
            if game[nr][nc]>=6:
                 left(wormholl(nr,nc))
            else:
                 return
            
def down(i,j):
    global bouns
    nr=i+dr[1]
    nc=j

    if 0<=nr<N and 0<=nc<N and visited[nr][nc]==False:
            visited[nr][nc]=True
            if game[nr][nc]==1 and i<nr and j==nc: #1번 블록 상하->우 
                 bouns+=1
                 right(nr,nc)
            if game[nr][nc]==1 and i==nr and nc<j: #1번 블록 우좌->상
                 bouns+=1
                 up(nr,nc)
            if game[nr][nc]==2 and i>nr and nc==j: #2번 블록 하상->우
                 bouns+=1
                 right(nr,nc)
            if game[nr][nc]==2 and i==nr and j>nc: #2번 블록 우좌->하
                 bouns+=1
                 down(nr,nc)
            if game[nr][nc]==3 and i>nr and nc==j:
                 bouns+=1
                 left(nr,nc)
            if game[nr][nc]==3 and i==nr and nc>j:
                 bouns+=1
                 down(nr,nc)
            if game[nr][nc]==4 and i==nr and nc>j:
                 bouns+=1
                 up(nr,nc)
            if game[nr][nc]==4 and i>nr and nc==j:
                 bouns+=1
                 left(nr,nc)
            if game[nr][nc]==0:
                 down[nr][nc]
            if game[nr][nc]>=6:
                 down(wormholl(nr,nc))
            else:
                 return

def up(i,j):
    global bouns
    nr=i+dr[0]
    nc=j

    if 0<=nr<N and 0<=nc<N and visited[nr][nc]==False:
            visited[nr][nc]=True
            if game[nr][nc]==1 and i<nr and j==nc: #1번 블록 상하->우 
                 bouns+=1
                 right(nr,nc)
            if game[nr][nc]==1 and i==nr and nc<j: #1번 블록 우좌->상
                 bouns+=1
                 up(nr,nc)
            if game[nr][nc]==2 and i>nr and nc==j: #2번 블록 하상->우
                 bouns+=1
                 right(nr,nc)
            if game[nr][nc]==2 and i==nr and j>nc: #2번 블록 우좌->하
                 bouns+=1
                 down(nr,nc)
            if game[nr][nc]==3 and i>nr and nc==j:
                 bouns+=1
                 left(nr,nc)
            if game[nr][nc]==3 and i==nr and nc>j:
                 bouns+=1
                 down(nr,nc)
            if game[nr][nc]==4 and i==nr and nc>j:
                 bouns+=1
                 up(nr,nc)
            if game[nr][nc]==4 and i>nr and nc==j:
                 bouns+=1
                 left(nr,nc)
            if game[nr][nc]==0:
                 up[nr][nc]
            if game[nr][nc]>=6:
                 up(wormholl(nr,nc))
            else:
                 return
                 

def right(i,j):
    global bouns
    nr=i
    nc=j+dc[3]

    if 0<=nr<N and 0<=nc<N and visited[nr][nc]==False:
            visited[nr][nc]=True
            if game[nr][nc]==1 and i<nr and j==nc: #1번 블록 상하->우 
                 bouns+=1
                 right(nr,nc)
            if game[nr][nc]==1 and i==nr and nc<j: #1번 블록 우좌->상
                 bouns+=1
                 up(nr,nc)
            if game[nr][nc]==2 and i>nr and nc==j: #2번 블록 하상->우
                 bouns+=1
                 right(nr,nc)
            if game[nr][nc]==2 and i==nr and j>nc: #2번 블록 우좌->하
                 bouns+=1
                 down(nr,nc)
            if game[nr][nc]==3 and i>nr and nc==j:
                 bouns+=1
                 left(nr,nc)
            if game[nr][nc]==3 and i==nr and nc>j:
                 bouns+=1
                 down(nr,nc)
            if game[nr][nc]==4 and i==nr and nc>j:
                 bouns+=1
                 up(nr,nc)
            if game[nr][nc]==4 and i>nr and nc==j:
                 bouns+=1
                 left(nr,nc)
            if game[nr][nc]==0:
                 right[nr][nc]
            if game[nr][nc]>=6:
                 right(wormholl(nr,nc))
            else:
                 return
def wormholl(i,j):
     for a in range(N):
          for b in range(N):
               if game[a][b]==game[i][j] and visited[a][b]==False:
                    return (a,b)


T = int(input())
for tc in range(1,T+1):
    N= int(input())
    game = [list(map(int,input().split())) for _ in range(N)]
    s_i,s_j=0,0
    visited = [[False]*N for _ in range(N)]
    max_bouns=-1
    bouns=0
    dr = [-1,1,0,0]
    dc = [0,0,-1,1]

    for i in range(N):
        for j in range(N):
            if game[i][j]==0 and visited[i][j]==False:
                s_i,s_j=i,j
                visited[s_i][s_j]=True
                ordinary_wall(s_i,s_j)

'''


def solve():
    # 테스트 케이스 개수 읽기
    line = input().strip()
    if not line: return
    T = int(line)
    
    # 방향 정의: 상(0), 하(1), 좌(2), 우(3)
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    
    # [핵심] 블록별 방향 전환 테이블
    # change_dir[블록번호][현재방향] = 바뀔방향
    change_dir = [
        [], # 0번 빈공간
        [1, 3, 0, 2], # 1번: 상->하, 하->우, 좌->상, 우->좌
        [3, 0, 1, 2], # 2번: 상->우, 하->상, 좌->하, 우->좌
        [2, 0, 3, 1], # 3번: 상->좌, 하->상, 좌->우, 우->하
        [1, 2, 3, 0], # 4번: 상->하, 하->좌, 좌->우, 우->상
        [1, 0, 3, 2]  # 5번: 상->하, 하->상, 좌->우, 우->좌 (모두 반전)
    ]

    for tc in range(1, T + 1):
        N = int(input().strip())
        
        # 1. 게임판 입력 (컴프리헨션 대신 정석 for문 사용)
        board = []
        for _ in range(N):
            row = list(map(int, input().split()))
            board.append(row)
        
        # 2. 웜홀 위치 사전 등록 (6~10번)
        # wormholes = { 6: [(r1, c1), (r2, c2)], ... }
        wormholes = {}
        for r in range(N):
            for c in range(N):
                val = board[r][c]
                if val >= 6:
                    if val not in wormholes:
                        wormholes[val] = []
                    wormholes[val].append((r, c))

        max_score = 0

        # 3. 모든 시작점과 모든 방향에 대해 시뮬레이션
        for r in range(N):
            for c in range(N):
                # 빈 공간(0)에서만 출발 가능
                if board[r][c] != 0:
                    continue
                
                for d in range(4):
                    score = 0
                    curr_r, curr_c = r, c
                    curr_d = d
                    
                    while True:
                        # 한 칸 이동
                        nr = curr_r + dr[curr_d]
                        nc = curr_c + dc[curr_d]
                        
                        # [벽 처리] 게임판 범위를 벗어나면 점수+1 하고 방향 반전
                        if nr < 0 or nr >= N or nc < 0 or nc >= N:
                            score += 1
                            # 방향 반전 (0<->1, 2<->3)
                            if curr_d == 0: curr_d = 1
                            elif curr_d == 1: curr_d = 0
                            elif curr_d == 2: curr_d = 3
                            else: curr_d = 2
                            
                            # 벽에 부딪힌 후 현재 좌표 업데이트
                            curr_r, curr_c = nr, nc
                            continue #점수는 계산해야하니까 다 하고 좌표값만 없던걸로 해주게됨 

                        # [종료 조건] 시작 위치로 돌아오거나 블랙홀(-1)을 만난 경우
                        if (nr == r and nc == c) or board[nr][nc] == -1:
                            if score > max_score:
                                max_score = score
                            break
                        
                        # [블록 처리] 1 ~ 5번 블록
                        if 1 <= board[nr][nc] <= 5:
                            score += 1
                            curr_d = change_dir[board[nr][nc]][curr_d]
                            curr_r, curr_c = nr, nc
                        
                        # [웜홀 처리] 6 ~ 10번 웜홀
                        elif board[nr][nc] >= 6:
                            num = board[nr][nc] #웜홀 번호마다 페어로 각 웜홀의 좌표값이 리스트에 저장되어있음 
                            hole_list = wormholes[num] 
                            # 현재 들어간 구멍이 아닌 반대편 구멍으로 순간이동 
                            if hole_list[0] == (nr, nc):
                                curr_r, curr_c = hole_list[1]
                            else:
                                curr_r, curr_c = hole_list[0]
                            # 방향은 그대로 유지
                        
                        # [빈 공간] 그냥 이동
                        else:
                            curr_r, curr_c = nr, nc
                            
        print(f"#{tc} {max_score}")

# 실행
solve()
