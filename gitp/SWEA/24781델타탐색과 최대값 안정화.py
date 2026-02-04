

'''
def fly_catcher(board, y, x):
    # 리스트를 만들지 않고 정수 변수에 바로 합산합니다.
    total_kill = 0
    
    # 세로 3칸 합산
    for a in range(y - 1, y + 2):
        total_kill += board[a][x]
        
    # 가로 3칸 합산 (중앙 y, x는 이미 더해졌으므로 제외하고 양옆만)
    total_kill += board[y][x - 1]
    total_kill += board[y][x + 1]
    
    return total_kill
    


T = int(input())
for w in range(1,T+1):
    N = int(input())
    for i in range(N): #행 만큼 반복 
        numbers = list(map(int, input().split()))
    best_y, best_x = 0,0
    max_killer = -1
    for r in range(1,N-1):
        for c in range(1,N-1):
            current_kill = fly_catcher(numbers, r, c)
            
            # [수정] 실시간으로 최대값 비교 및 좌표 저장
            if current_kill > max_killer:
                max_killer = current_kill
                best_y, best_x = r, c
                
    print(f'#{w} {max_killer} {best_y} {best_x}')
                      
'''


'''
T = int(input())

for w in range(1, T + 1):
    N = int(input())
    # 1. 2차원 배열로 전체 파리 정보 저장
    board = [list(map(int, input().split())) for _ in range(N)]
    
    max_flies = -1
    best_y, best_x = 0, 0
    
    # 2. 십자가 방향 정의 (중앙, 상, 하, 좌, 우)
    dy = [0, -1, 1, 0, 0]
    dx = [0, 0, 0, -1, 1]
    
    # 3. 전체 좌표 탐색 (인덱스 범위를 벗어나지 않게 주의)
    for y in range(1, N - 1): # 상하 1칸씩 필요하므로 1 ~ N-2 까지 #3*3안에서 보니까 #y,x는 현재 좌표값임 
        for x in range(1, N - 1): # 좌우 1칸씩 필요하므로 1 ~ N-2 까지
            
            # 현재 좌표 (y, x)에서 잡는 파리 수 계산
            current_sum = 0
            for i in range(5): #현재 좌표의 범위는 움직일 수 있는 방향의 인덱스 값 
                ny = y + dy[i] #인덱스 값 구해서 
                nx = x + dx[i]


                if 0 <= ny < N and 0 <= nx < N:
                    current_sum += board[ny][nx]
                
            
            # 4. 최대값 갱신 및 좌표 저장
            if current_sum > max_flies:
                max_flies = current_sum
                best_y, best_x = y, x
            # 문제 조건에는 없지만, 만약 최대값이 같다면? 
            # 보통 좌표가 작은 것을 출력하라는 조건이 붙기도 합니다.
                
    print(f'#{w} {max_flies} {best_y} {best_x}')
'''

T_input = input().strip()
if T_input:
    T = int(T_input)
    for w in range(1, T + 1):
        N = int(input().strip())
        
        # 1. 격자 정보 입력 받기
        board = []
        for _ in range(N):
            board.append(list(map(int, input().split())))
        
        max_flies = -1 #최대값 -1로 안정화 
        best_y, best_x = 0, 0
        
        # 2. 십자가 방향 정의 (중앙, 상, 하, 좌, 우)
        dy = [0, -1, 1, 0, 0]
        dx = [0, 0, 0, -1, 1]
        
        # 3. 모든 좌표 (0 ~ N-1)를 중심으로 전수 조사
        # range(1, N-1)이 아니라 range(N)이어야 테두리까지 검사합니다.
        for y in range(N):
            for x in range(N):
                current_sum = 0
                
                # 십자가 5칸 확인
                for i in range(5):
                    ny = y + dy[i]
                    nx = x + dx[i]
                    
                    # [핵심] 격자 범위 안에 있는 경우에만 합산
                    if 0 <= ny < N and 0 <= nx < N:
                        current_sum += board[ny][nx]
                
                # 4. 최대값 갱신
                # > 를 사용하면 빈도수가 같을 때 먼저 발견된(좌표가 작은) 값이 유지됩니다.
                if current_sum > max_flies:
                    max_flies = current_sum
                    best_y, best_x = y, x
                    
        print(f'#{w} {max_flies} {best_y} {best_x}')