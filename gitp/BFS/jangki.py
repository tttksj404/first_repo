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



    '''


dy = [-1, 1, 0, 0]
dx = [0, 0, -1, 1]

def dfs(cur, n):
    # [탈출 조건] 포가 3번 넘었으면(n=3) 더 이상 갈 필요 없으니 종료!
    if n == 3:
        return

    # 4방향(상하좌우) 하나씩 검사해보자
    for i in range(4):
        jumped = False  # 아직 '다리'(넘을 기물)를 발견 못 했다는 뜻이야
        
        # 현재 위치에서 해당 방향으로 장기판 끝까지 쭉~ 훑어봐 (j는 거리)
        for j in range(1, N + 1):
            ny = cur[0] + dy[i] * j
            nx = cur[1] + dx[i] * j
            
            # 장기판 범위 안에 있을 때만 따져야겠지?
            if 0 <= ny < N and 0 <= nx < N:
                
                # 1. 아직 다리를 안 넘었을 때
                if not jumped:
                    # 기물(1)을 만났다! 드디어 넘을 '다리'를 찾았어!
                    if matrix[ny][nx] == 1:
                        jumped = True # 이제부터는 '넘은 상태'야
                        continue      # 다리 바로 위에는 못 앉으니까 다음 칸으로 PASS
                
                # 2. 이미 다리를 하나 넘었을 때 (여기서부터 착지 가능)
                if jumped:
                    # Case A: 다리를 넘었는데 또 기물(1)을 만났다? -> "이놈 잡았다!"
                    if matrix[ny][nx] == 1:
                        # 이 기물 위치는 포가 잡을 수 있는 곳이야. 체크!
                        checked[ny][nx] = True
                        
                        # [백트래킹 시작]
                        matrix[ny][nx] = 0  # 기물을 잡았으니까 잠시 빈칸(0)으로 치워둬
                        dfs((ny, nx), n + 1) # 잡은 그 자리에서 다음 점프(n+1) 시작!
                        matrix[ny][nx] = 1  # 탐색 끝나고 돌아오면 다시 기물을 원래대로(1) 복구!
                        
                        # 기물을 하나 잡으면 그 뒤는 못 넘어가니까 이 방향은 여기서 끝!
                        break
                    
                    # Case B: 다리를 넘었는데 빈 공간(0)이다? -> "잠시 쉬어가기"
                    else:
                        # 빈 곳에 착지해서 다음 이동(n+1)을 준비해
                        dfs((ny, nx), n + 1)

# --- 메인 실행부 ---
T = int(input())
for t in range(T):
    N = int(input())
    matrix = [list(map(int, input().split())) for i in range(N)]
    
    # 1. 일단 우리 '포'(값=2)가 어디 있는지부터 찾자
    for i in range(N):
        for j in range(N):
            if matrix[i][j] == 2:
                cur = (i, j)
    
    # 잡을 수 있는 기물 위치를 기록할 판 (중복 체크용)
    checked = [[False] * N for i in range(N)]
    cnt = 0
    
    # 2. DFS 탐색 시작! (시작점, 이동횟수 0)
    dfs(cur, 0)
    
    # 3. 전체 판을 돌면서 포가 잡을 수 있다고 표시(True)된 곳만 세어보자
    for i in checked:
        for j in i:
            if j == True:
                cnt += 1
                
    print(f'#{t+1} {cnt}')
    '''