'''
폭탄이 터지면 터진곳은 _에서 %로 표시 
@폭탄의 위치를 정하면 그걸 기점으로- 폭탄 위치를 배열 탐색으로 찾기 찾으면 인덱스 값 리스트에 담기 
k만큼 가운데,상,하,좌,우 폭발- 
dr = [-k,k,0,0]
dc = [0,0,-k,k]
1.하지만 #있는 곳은 막힌다는 조건
2.거기다가 %로 바뀌려면 상하좌우에 _가 있어야한다는 조건도 필요 

'''



T = int(input())
for w in range(1,T+1):
    N,M = map(int,input().split()) #N은 세로 행 M은 가로 열
    k = int(input()) #화력
    maps = [list(map(str, input())) for _ in range(N)] 
    dr = [-k,k,0,0]
    dc = [0,0,-k,k]
    for i in range(N):#0,1,2
        bombs_i=0
        bombs_j=0
        for j in range(M):#0,1,2,3,4
            if maps[i][j] == "@":
                bombs_i = i
                bombs_j= j
                for a in range(4):
                    nr = i+dr[a]
                    nc = j+dc[a]
                    if nr>N-1 or nr<0 or nc>M-1 or nc<0:
                        continue
                    else:   
                        if maps[nr][nc] == "#":
                            break
                        else:
                            maps[nr][nc] = "%"
    print(f'#{w}')
    print(*maps)





