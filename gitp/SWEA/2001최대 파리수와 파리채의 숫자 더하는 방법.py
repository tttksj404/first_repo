'''
t개수가 주어지고
n*n(배열 전체의 개수)와 m*m(파리채의 크기)가 주어짐 
n만큼의 가로 세로의 배열 각 수 주어짐 

box_two = []
for r in range(0, N, M): # 0, 3, 6
            for c in range(0, N, M): # 0, 3, 6
                box = []
                for i in range(M):
                    for j in range(M):
                        box.append(fly_area[r+i][c+j])
                storage = sum(box)
                box_two.append(storage)

ans =max(box_two)


이걸로 파리채 위치 잡고, max값 반환 하면됨 
max_val = 0 
if 

'''

T = int(input())
for w in range(1,T+1):

    N , M = map(int, input().split())
    fly_area = [] #fly_area라고 하는 리스트 안에 계속 추가해줘야하는데 fly_area = list 이런식으로 입력을 받으면 계속 원래 값은 지워지고, 축척이 안됨 

    for _ in range(N):
        fly_area.append(list(map(int, input().split())))
    
    max_flies = 0 #최대 파리수를 저장
    for r in range(N-M+1):  #여기선 파리채의 범위를 결정 해주기 
        for c in range(N-M+1): 
            current_sum = 0
            for i in range(M): #파리채 안의 숫자들 더해주는 거 
                for j in range(M):
                    current_sum+=(fly_area[r+i][c+j])
            if current_sum >= max_flies:
                max_flies = current_sum

    print(f'#{w} {max_flies}')
  
    
'''
import sys
sys.stdin = open("input.txt", "r")

# 상하좌우 델타
dy = [-1, 1, 0, 0]
dx = [0, 0, -1, 1]

T = int(input())

for tc in range(1, T + 1):
    N = int(input())
    arr = [list(map(int, input().split())) for _ in range(N)]

    max_y, max_x, max_total = 0, 0, 0

    # sy, sx : 파리채를 치는 지점
    for sy in range(N):
        for sx in range(N):
            # (sy, sx) + 상하좌우 값 -> 더한다.
            total = arr[sy][sx]

            for i in range(4):
                new_y = sy + dy[i]
                new_x = sx + dx[i]

                # 해당 방향의 좌표가 범위를 벗어나면 continue
                if new_y < 0 or new_y >= N or new_x < 0 or new_x >= N:
                    continue

                total += arr[new_y][new_x]

            # 최대값 갱신
            if total > max_total:
                max_y = sy
                max_x = sx
                max_total = total

    print(f"#{tc} {max_total} {max_y} {max_x}")
    '''