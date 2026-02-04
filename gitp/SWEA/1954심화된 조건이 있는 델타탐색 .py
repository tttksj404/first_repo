'''
테스트 개수
테스트 개수 만큼 반복
받은 N  
for for 2번 반복해서 1부터 4까지 이어감 
x

우하좌상 반복되는데
조건으로 벽에 부딪히면 멈춤
'''

T = int(input())
for w in range(1,T+1):
    N = int(input())
    snaill = [[0]*N for _ in range(N)]
    dr = [0,1,0,-1] #우->하->좌->상 행값
    dc = [1,0,-1,0] #열값

    r,c = 0,0
    dist = 0

    for num in range(1, N*N+1): #1,2,3...N까지 숫자 넣기 
        snaill[r][c] = num
        nr = r+ dr[dist]
        nc = c+ dc[dist]

        if nr<0 or nr>=N or nc<0 or nc>=N or snaill[nr][nc] != 0: #snail이 0으로 이뤄졌는데 거기에 숫자 하나씩 들어갈때 
            #0이 아닌 다른 숫자가 채워지기에 
            dist = (dist+1)%4 #0,1,2,3 반복시 우하좌상인데 각각 넣으면 1,2,3,0 되서 하좌상우로 반복됨 
            nr = r+dr[dist]
            nc = c+dc[dist]

        r,c = nr, nc
    
    print(f'#{w}')
    for row in snaill:
        print(*row)



