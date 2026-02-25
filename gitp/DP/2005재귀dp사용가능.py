'''
n에 따라서 출력되는 줄의 개수 n개 이고, 
n만큼 아래 메커니즘의 반복출력
출력되는 값의 시작과 끝은 항상 1이고 그 다음 값은 n,n+1인덱스의 값을 더해준것 

출력되는 리스트는 그 개수를 +=1 해주고 
그안에 내용물은 시작 0,1,2,3,4 인덱스중에서 1인덱스값이 궁금하면 이전 리스트를 스택에다가 담아놓고 
그 스택에서 1인덱스와 그 값의 -1인덱스값을 더한 값이 현재 리스트의 1인덱스의 값이 된다는 메커니즘
작성해주면됨 
그걸 마지막 인덱스(len-1)까지만 반복해줘서 내용 채워주면된다.
'''

T = int(input())
for w in range(1,T+1):
    n = int(input()) #n만큼 반복출력 줄의개수 
    stack = []
    now_list = []


    #출력값의 시작과 끝값은 항상1 idx 0은 1 idx 
    print(f'#{w}')
    yesterday_list = [1]
    print(*yesterday_list)
    for a in range(2,n+1):
        now_list = [1]*a
        for idx in range(1,len(now_list)-1):
            now_list[idx]=yesterday_list[idx-1]+yesterday_list[idx] #재귀로 풀어줘도 괜찮음 
        print(*now_list)
        yesterday_list=now_list



        
'''

T = int(input())

for t in range(1, T + 1):
    N = int(input())
    print(f'#{t}')
    
    row = [1]  # 첫 번째 줄
    print(*row)
    
    for _ in range(N - 1):
        # 윗줄의 양옆에 0을 붙인 두 리스트를 만들어 같은 인덱스끼리 더함
        # zip([0,1,2,1], [1,2,1,0]) -> (0,1), (1,2), (2,1), (1,0)
        row = [x + y for x, y in zip([0] + row, row + [0])]
        print(*row)


'''
            
'''


T = int(input())

for t in range(1, T + 1):
    N = int(input())
    
    # 1. 메모이제이션을 위한 2차원 리스트(DP 테이블) 초기화
    # N=4라면 4x4 크기의 0으로 채워진 표를 만듭니다.
    dp = [[0] * N for _ in range(N)]
    
    print(f'#{t}')
    
    for i in range(N):
        for j in range(i + 1):
            # 2. 베이스 케이스: 줄의 시작과 끝은 1
            if j == 0 or j == i:
                dp[i][j] = 1
            else:
                # 3. 점화식: 윗줄의 왼쪽 위 + 바로 위 값을 더함
                # 이전에 계산된 dp[i-1]의 값들을 재활용하는 것이 DP의 핵심!
                dp[i][j] = dp[i-1][j-1] + dp[i-1][j] #이전 행의 이전 열값 + 이전행의 지금 열값 
        
        # 이번 줄 출력을 위해 0이 아닌 값만 골라서 출력
        print(*(dp[i][:i+1]))

'''
'''

T = int(input()) 
for c in range(T):
    N = int(input())
    number = [[1 for j in range(i+1)] for i in range(N)] #미리 1을 넣어두기 
    for x in range(N):
        for y in range(x):
            if y != 0 and y != N-1: #맨 초반이랑 맨 끝값아니라면 숫자 채우기라서 
                number[x][y] = number[x-1][y] + number[x-1][y-1]
 
    print(f'#{c+1}')
    for k in range(N):
        print(*number[k])
'''