'''
1+2n으로 처음부터 시작하는거
N =5면 n은 0,1,2 즉 3번째임 
(N-1)/2+1= n 이러면 3번째 
1은 1   
2는 1,3,1
3은 1,3,5,3,1  ->여기가 5임 


가장 가운데 행을 찾고 N//2 -> 가운데 행 번호 0,1,2 N이 5면 0,1,2,3,4 중 2가 가운데 행이므로
가운데 행까지 0행 1 1행 3 2행 5    / 3행이 가운데 이므로 3행까지 7이고 다시 4행부터는 되돌아가는 for 문
근데 0행의 3열에서 1 이고 / 1행의 2,3,4열 

start하고 end 를 바꿔주면서 하기 그리고 중간 행부터 시작해서 위로 그리고 아래로 
'''


T= int(input())
for tc in range(1,T+1):
    N= int(input())
    farm = [list(map(int, input())) for _ in range(N) ]
    #N*N에서 일단 찾기
    start = 0
    end = N
    total=0
    for i in range(N//2,N): #0,1,2행까지 증가 반복 1,3,5
        for j in range(start, end):
            total+=farm[i][j]
        start+=1
        end-=1
        #따로 끝내는 조건 필요x 애초에 행이 그만큼만 반복하니까 
    start,end = 0,N
    for a in range(N//2,-1,-1):
        for b in range(start,end):
            if a == N//2:
                pass
            else:
                total+=farm[a][b]
        start+=1
        end-=1
    print(f'#{tc} {total}')


'''
for tc in range(1, T + 1):
    N = int(input())
    farm = [list(map(int, input())) for _ in range(N)]
    mid = N // 2
    total = 0

    for i in range(N):
        # 중앙으로부터 떨어진 거리(절대값)만큼 양 끝에서 제외됨
        offset = abs(mid - i)
        # 시작: offset, 끝: N - offset
        total += sum(farm[i][offset : N - offset]) #시작~끝-1까지가져오므로 이렇게도 가능 
        
    print(f'#{tc} {total}')

'''
'''
for tc in range(1, T + 1):
    N = int(input())
    farm = [list(map(int, input())) for _ in range(N)]
    mid = N // 2
    total = 0

    for i in range(N):
        for j in range(N):
            # 행과 열의 중앙으로부터의 거리 합이 mid 이하면 수확 범위!
            if abs(i - mid) + abs(j - mid) <= mid:  #다이아몬드 처럼 행과 열 모두 중앙값에서 부터 퍼져있는 거리가 같으므로
            #결국 중앙값과의 거리안에 행과 열이 전부 있어야 해서 
            #마치 중앙에서 출발해서 완전히 직선으로가면 물론 더 멀리가겠지만 / 직선 갔다가 우회전 혹은 좌회전하면 그만큼 갈 수 있는 거리가 줄어들어서

                total += farm[i][j]
    print(f'#{tc} {total}')

수학에서 두 점 $(x_1, y_1)$과 $(x_2, y_2)$ 사이의 맨해튼 거리는 다음과 같이 정의합니다:d = |x_1 - x_2| + |y_1 - y_2|
중앙 지점: (mid, mid)현재 확인 중인 칸: (i, j)둘 사이의 맨해튼 거리: |i - mid| + |j - mid|
    
'''
