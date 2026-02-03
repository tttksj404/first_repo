

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



