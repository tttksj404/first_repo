'''
포가 상하좌우로 while 쭉직선 방향으로 이동 1의 개수 세서 1 2개 이상이면 1의 개수-1 만큼 해당 위치의 해당 방향에서 졸병을 
먹을 수 있는 방법임 
그렇게 한 위치에서 상하좌우 먹을 수 있는 법 total로 더해서 구하고 

위치에 따라서 먹을 수 있는법 전부 total로 뽑으면 됨 

포는 3번만 이동가능함 
이동 패턴 총 3번으로 제한 

이동 조건은 1바로 다음 0 이 있어야함 1바로 다음 1이 있는 경우, 벽에 1이 있는 경우만 제외하면 나머지는 이동가능
1을 잡을때 
1회 이동한 경우 첫빠따에 바로 1잡음
2회 이동한 경우 처음은 0으로 이동 두번째에 바로 1잡음
3회 이동한 경우 처음,두번째는 0으로 이동 세번째에 바로 1잡음
전부 나눠서 봐야함 

포의 위치 정해주고 거기에 대해서 진행하는 BFS문제 
'''



#그 자리에서 바로 점프쳐서 1 먹어야하는 첫번째 경우
def dfs(i,j,count,eaten_set):
    if count==3:
        return
   
        
    for a in range(4):
        bridge_found = False
        nr=i+dr[a]
        nc=j+dc[a]
        
        
        while 0<=nr<N and 0<=nc<N:
            if pan[nr][nc]==1:
                bridge_found=True
                break
            nr+=dr[a]
            nc+=dc[a]
        if bridge_found:
            nr+=dr[a]
            nc+=dc[a]
        
            while 0<=nr<N and 0<=nc<N: #이상태로 다시 1찾기
                if pan[nr][nc]==0:
                    dfs(nr,nc,count+1,eaten_set)
                
                elif pan[nr][nc]==1:
                    eaten_set.add((nr,nc))

                    pan[nr][nc]=0 #일단 먹힌자리는 0으로 돌려주기 왜냐면 처음부터 쭉 한쪽으로만 가는게 아니라 점프한다는 메커니즘을 
                    #가지고 오기 때문 일단 실제로는 계속 한 방향으로만 가다가 1발견하면 브릿지 찾았으니까 이동가능하고, 
                    #그다음 바로 그 방향 위 혹은 진행하던 방향의 바로 한칸뒤 0이면 그 지점부터 다시 사방탐색 가능 
                    #1이면 거기 먹히고 거기서 사방탐색 시작 
                    dfs(nr,nc,count+1,eaten_set)
                    pan[nr][nc]=1
                    #가장 핵심 !!!!
                    #사실상 dfs를 들어가도 dfs가 계속 반복해서 들어간다고 생각하는데 아님 
                    #하나의 dfs1가 재귀 dfs1-1로 들어가면 일단 1은 끝났으니까 par[nr][nc]=1를 시행하고 그다음에 dfs1-1시행하는것 

                    # 사실상 for 문에서 dfs1이 상방향을 봤으면 다음 재귀dfs에서는 상하좌우중 하나를 볼꺼고 그게 이어져서 
                    #각 dfs가 끝나고는 pan[nr][nc]가 백트레킹해서 복구하고 이게 dfs1, 각dfs가 다른 방향볼거에는 영향 안주도록 만드는거

                    break
                #여긴 if pan[nr][nc]==0일때 즉 빈칸일때 경우이고, 다른 재귀까지 다 끝나도 원래dfs1은 기존의 방향대로 하며 while문에서 안벗어나고 
                #단지 한칸 이동해서 while 다시 돌리게 됨 
                nr+=dr[a]
                nc+=dc[a]

                #위에서 elif에 맞으면 쫄이 있다는 소리고 그럼 break되서 맨위 for 구문으로 넘어가게됨 



dr=[-1,1,0,0]
dc=[0,0,-1,1]
T = int(input())
for tc in range(1,T+1):
    N=int(input())
    pan = [list(map(int,input().split())) for _ in range(N)]
    si,sj=0,0


    for i in range(N):
        for j in range(N):
            if pan[i][j]==2:
                si,sj=i,j
                pan[i][j]=0
                break
    # 먹은 쫄들 좌표를 담을건데 중복해서 담았을 수도 있기에 이를 방지하기 위함 특히 백트레킹은 dfs1 자체에서만 작동하기에
    # dfs1 이랑 dfs1-1가 중복되서 값을 담았을 수 있음 그걸 방지하기위해 
    eaten_set = set()
    dfs(si,sj,0,eaten_set)
    print(f'#{tc} {len(eaten_set)}')