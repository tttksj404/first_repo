'''
먼저 출발지인 2찾고, 2에서 다음 으로 0찾아서 계속 상하좌우탐색해서 0으로 나아가고 
0으로 가면 그게 다시 출발지로 리셋 
그걸 3을 찾을 때 까지 반복하기 whlie 범위가 3될때까지
가능하면 1

다 돌았는데 3못찾으면 0출력

'''
'''
def dfs(r,c):
    global ans
    if maze[r][c]==3:
        ans =1
        return
    
    check[r][c]=True
    for i in range(4):
        nr,nc= r+dr[i], c+dc[i]
        if 0<= nr <=N-1 and 0<= nc <=N-1:
            if maze[nr][nc]==0 and not check[nr][nc]:
                dfs(nr,nc)
                if ans ==1:
                    return

T = int(input())
for tc in range(1,T+1):
    N = int(input())
    maze = [list(map(int, input().strip())) for _ in range(N)]
    a,b = -1,-1 #시작점
    dr = [-1,1,0,0] #상하좌우
    dc = [0,0,-1,1]
    check = [[False]*N for _ in range(N)]
    ans = 0

    for i in range(N):
        for j in range(N):
            if maze[i][j] == 2:
                a,b=i,j #시작점 ab쓰기
                break
        if a!= -1:
            break
    dfs(a,b)

    print(f'#{tc} {ans}')
'''


T = int(input())
for tc in range(1,T+1):
    N = int(input())
    maze = [list(map(int, input().strip())) for _ in range(N)]
    a,b = -1,-1 #시작점
    dr = [-1,1,0,0] #상하좌우
    dc = [0,0,-1,1]
    check = [[False]*N for _ in range(N)]
    ans = 0

    for i in range(N):
        for j in range(N):
            if maze[i][j] == 2:
                a,b=i,j #시작점 ab쓰기
                break
        if a!= -1:
            break

    stack = [(a,b)]
    
    while stack:
        curr_r,curr_c = stack.pop()
        if maze[curr_r][curr_c]==3:
            ans=1
            break
        for i in range(4):
            nr,nc = curr_r+dr[i], curr_c+dc[i]

            if 0 <= nr < N and 0 <= nc < N:
                if maze[nr][nc] !=1 and not check[nr][nc]: #이미 false로 있는 상태에서 그 좌표값이 check에 없다면 true라는 소리
                    check[nr][nc]=True
                    stack.append((nr,nc))
    print(f'#{tc} {ans}')

