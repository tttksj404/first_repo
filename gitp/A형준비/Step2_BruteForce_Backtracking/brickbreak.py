'''
일단 N 구슬개수 / W열 가로 / H행 세로 

1.중력 구현 함수

2.dfs
    중력 구현전에 백트레킹 시도 해야됨 
    가지치기 조건-> 떨어진 벽돌 nr,nc에 2보다 크거나 같은게 있는지 없으면 x 

    기저조건->N==0이 될때 

    다른 경우는 그냥 while문으로 진행 그안에서 visited true에다가 중력구현 전 전체 map 저장해놓고 / 여기다가 중력구현 함수
    dfs(nr,nc,N,board)이런식 
    다음visited=false해주고 백트레킹 중력구현 전 전체map 불러오도록 하기


'''
def apply_gravity(b):
    for c in range(W):
        idx = H - 1
        for r in range(H-1, -1, -1):
            if b[r][c] > 0:
                # 아래로 밀기 로직
                b[idx][c], b[r][c] = b[r][c], b[idx][c]
                if idx != r: b[r][c] = 0
                idx -= 1

def boom(r, c, b):
    power = b[r][c]
    b[r][c] = 0
    if power <= 1: return
    
    for a in range(4):
        nr, nc = r, c
        for _ in range(power - 1): # 숫자만큼 뻗어나가며 연쇄 폭발
            nr, nc = nr + dr[a], nc + dc[a]
            if 0 <= nr < H and 0 <= nc < W:
                if b[nr][nc] > 0:
                    boom(nr, nc, b) # 연쇄적으로 다른 벽돌도 boom!
            else: break

def dfs(ball, current_board):
    global min_bricks
    
    # 기저 조건: 구슬 다 씀 or 벽돌 0개
    if ball == 0:
        cnt = 0
        for r in range(H):
            for c in range(W):
                if current_board[r][c] > 0:
                    cnt += 1
        
        if cnt < min_bricks:
            min_bricks = cnt
        return

    for c in range(W): # 구슬을 던질 열(W) 선택
        # 해당 열의 맨 위 벽돌 찾기
        r = 0
        while r < H and current_board[r][c] == 0:
            r += 1
        
        if r < H: # 맞출 벽돌이 있다면
            next_board = []
            for row in current_board:
                next_board.append(row[:]) #여기가 백트레킹자리 
            boom(r, c, next_board)      # 1. 팡! (연쇄 폭발)
            apply_gravity(next_board)   # 2. 스르륵 (중력은 폭발 다 끝나고 한 번만)
            dfs(ball - 1, next_board) # 3. 다음 구슬 던지기
        else: # 벽돌이 없으면 다음 열 시도해도 되지만, 결과는 같으니 갱신만
            cnt = 0
            for row_idx in range(H):
                for col_idx in range(W):
                    if current_board[row_idx][col_idx] > 0:
                        cnt += 1
            if cnt < min_bricks:
                min_bricks = cnt        
            #row.count(0)-> 한줄에 빈공간이 몇개인지 셈 



dr=[-1,1,0,0]
dc=[0,0,-1,1]

T=int(input())
for tc in range(1,T+1):
    N,W,H = map(int,input().split())
    board = [list(map(int,input().split())) for _ in range(H)]
    min_bricks=99999999999

    
    dfs(N,board)
    print(f'#{tc} {min_bricks}')
    
    


