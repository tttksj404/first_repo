'''
t의 개수 
만큼 반복
map의 크기 n
map = [list(map(int,input().split())) for _ in range(n)]
count=1 #등산로의 길이
현재위치 r,c= 0,0
#상하좌우
dr = [-1,1,0,0]
dc = [0,0,-1,1]
탐색해서 현재 위치보다 nr,nc가 작다면 이동하는데 
1. max_nr_nc = 0이면서 nr,nc를 돌면서 안에서 map[nr][nc] >= max_nr_nc 이면 max_nr_nc = map[nr][nc]해주기 현재위치를 r=nr c=nc로 바꿔주기 count +=1도
2.만약에 현재 위치 값보다 어떤 nr,nc들이 작지 않다면 그건 break 치고, 
'''


T = int(input())
for w in range(1,T+1):
    N = int(input())
    maps = [list(map(int,input().split())) for _ in range(N)]
    count_list = []
    r,c = 0,0 #현재 위치
    dr = [-1,1,0,0]
    dc = [0,0,-1,1]
    #for z in range(N): #초반 시작점 알려주기 
        #r,c = 0,z  #시작점은 지도의 모든 부분이 될 수 있기 때문에 주의하기 일부분만 하지 않기
    max_count = 0
    for i in range(N):
        for j in range(N):
            count = 1
            r,c=i,j 
            while True:
                min_val = 999 #절대로 나올 수 없는 가장 큰값을 넣어서 첫번째로 검사하는 나보다 낮은 칸이 무조건 min_val이 될 수 있도록 만들려고
                target_r, target_c = -1,-1 #리스트 인덱스가 0부터 시작하기에 -1은 존재할 수 없는 위치로 유효한 값을 찾지 못했다는 신호
                for a in range(4):
                    nr = r+dr[a]
                    nc = c+dc[a]
                    if nr<0 or nr>N-1 or nc<0 or nc>N-1:
                        continue
                    if maps[r][c]> maps[nr][nc]:
                        if maps[nr][nc]<min_val:
                            min_val = maps[nr][nc]
                            target_r, target_c =nr,nc # 최소, 최댓값 및 좌표까지 조건에 따라 갱신!

                if target_r !=-1: #초반부 값(-1)이 아니라 이동가능한 부분이 존재한다면 target_r이 nr일 것이기 때문에 
                    r,c = target_r,target_c
                    count+=1
                else: #초반부에서 못벗어났다는 소리이기에 나아갈 방향이 전부 막혔다는 증거 
                    break
            if count> max_count:
                max_count =count
                         #현재 위치보다 작은 주변부분 다 저장해놓기



                    #if maps[r][c]>maps[nr][nc]:
                        #min_nr_nc.append(maps[nr][nc])
                        #if min(min_nr_nc) == maps[nr][nc]:
                            #r=nr
                            #c=nc
                            #count+=1
                    
    
    print(f'#{w} {max_count}')






