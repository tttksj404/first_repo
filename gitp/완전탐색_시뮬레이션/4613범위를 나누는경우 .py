'''
N*M에서 N은 행 M은 열
위에서 몇줄 흰색
그다음 몇줄 파랑
그다음 빨강
처음과 마지막은 각각 흰색, 빨간색이고

파랑과 빨강의 기준만 설정하면 이부분을 완전탐색으로 돌아가면서 설정하고 변하는 최소값찾아야함 
다만 두개의 기준은 서로 같은 행일 수 없다는점과 파랑의 행<빨강의 시작행 이라는점 주의



T=int(input())
for tc in range(1,T+1):
    N,M= map(int,input().split())
    flag = [list(map(str, input().strip())) for _ in range(N)]
    total_change = 0
    min_change =2500
    some = 0

    #일단 맨 위랑 맨 아래는 흰,빨이니까 이걸로 바꿔야하는 깃발 갯수 먼저 구해놓기
    for z in range(M):
        if flag[0][z] != "W":
            some+=1
        if flag[N-1][z] !="R":
            some+=1
    
    #파랑의 시작점 기준 어딘지 정하는 완전탐색/ 0번 아닌 1번 행부터 그리고 마지막 행이전 행까지만 탐색
    #이렇게 파랑 범위 설정하면 자동으로 흰색, 빨간색 변화값 정해짐
    blue_start=0
    blue_end=0
    for s in range(1, N-1):
        blue_start=s
        for e in range(blue_start+1,N-1):
            blue_end=e
'''
T = int(input())

for tc in range(1, T + 1):
    N, M = map(int, input().split())
    flag = [input() for _ in range(N)]
    
    min_paint = float('inf') # 최솟값을 찾기 위해 아주 큰 수로 시작

    # i는 흰색 구역이 끝나는 행 번호
    # (최소 파란색 한 줄, 빨간색 한 줄은 남겨야 하므로 N-3까지만 가능)
    for i in range(0, N - 2):
        
        # j는 파란색 구역이 끝나는 행 번호
        # (흰색 다음부터 시작해서, 빨간색 한 줄은 남겨야 하므로 N-2까지만 가능)
        for j in range(i + 1, N - 1):
            
            # 현재 정해진 i와 j 경계선을 기준으로 새로 칠해야 하는 칸 세기
            current_paint = 0
            
            for row in range(N):
                if row <= i:
                    # 흰색 구역: 'W'가 아닌 개수 세기
                    for char in flag[row]:
                        if char != 'W':
                            current_paint += 1
                            
                elif i < row <= j:
                    # 파란색 구역: 'B'가 아닌 개수 세기
                    for char in flag[row]:
                        if char != 'B':
                            current_paint += 1
                            
                else:
                    # 빨간색 구역: 'R'가 아닌 개수 세기
                    for char in flag[row]:
                        if char != 'R':
                            current_paint += 1
            
            # 모든 경우의 수 중 가장 작은 값 보관
            if current_paint < min_paint:
                min_paint = current_paint

    print(f"#{tc} {min_paint}")





