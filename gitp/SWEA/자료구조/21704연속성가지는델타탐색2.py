'''
상하좌우
dr = [-1,1,0,0]
dc = [0,0,-1,1]
그리고 연속성 가지는 값으로
*p만큼 반복치고
nr = r +dr[i]*p
nc = c +dc[i]*p
'''
T = int(input())
for w in range(1,T+1):
    N,P = map(int, input().split()) #N은 map크기 P는 폭탄의 연속범위
    town = [list(map(int,input().split())) for _ in range(N) ]
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    r,c=0,0
    virus_sum = 0
    virus_list = []
    for i in range(N):
        for j in range(N):
            r,c=i,j
            virus_sum+=town[i][j]
            for a in range(4):
                for b in range(1,P+1):
                    nr = r+dr[a]*b
                    nc = c+dc[a]*b

                    if 0<=nr<=N-1 and 0<=nc<=N-1:
                        virus_sum+=town[nr][nc]
            virus_list.append(virus_sum)
            virus_sum=0
            ans = max(virus_list)
    print(f'#{w} {ans}')



