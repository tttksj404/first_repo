'''
퀸이 움직이는건 가로 ,세로, 대각선 아래 , 대각선 위 
visied 해서 겹치면 안되는데 하나씩 놓고 거기 전부다 visited 처리후 다음 꺼 놓고 이런식
결국 N개의 퀸이 제한임  퀸 하나놓을때마다 임의의 놓는 퀸을 depth라 하면 
퀸 하나놓을때마다 depth-=1 근데 놓을 때 (즉 조건이 안만족해서 끝까지 내려오면) -> 이때 depth==0인지 아닌지 확인후
아니면 
다시 백트레킹해서 처음부터 초반과는 다른 위치에 퀸 놓게 만들기 여기서 visited 백트레킹으로 복구 시켜줘야 처음과 다른 위치 퀸 놓음
근데 방문하지 않은 위치에 다음게 들어가야하니까 조건 필수 


#상하좌우 / 대각선 우상 / 대각선 우하 / 대각선 좌하 / 대각선 좌상
dr= [-1,1,0,0,-1,1,1,-1]
dc= [0,0,-1,1,1,1,-1,-1]

def dfs(depth):
    global flag
    global total


    for i in range(N):
        for j in range(N):
            if visited[i][j]==False:
                visited[i][j]=True
                si,sj=i,j #퀸의 시작값 
                depth-=1
                queen(si,sj)

                if depth==0 and flag==True: #그 퀸은 다른곳 침범하기 때문에 소용없음 다른곳에 놔야함 
                    dfs(depth+1)
                    visited[i][j]=False
    if depth!=0: #다 돌았는데 퀸 안놔진게 있으면 그건 안된다는거
        return 0 
    if depth==0:
        total+=1
        dfs(depth)
        






def queen(i,j): #퀸의 위치에 따라 visited 찍을 위치 계산하는 함수
    global flag
    for a in range(8):
        nr=i+dr[a]
        nc=j+dc[a]

        while 0<=nr<N and 0<=nc<N:
            if visited[nr][nc]==False:
                nr=nr+dr[a]
                nc=nc+dc[a]
                visited[nr][nc]=True
            else: #만약 퀸 공격로가 이미 다른 퀸에 의해 점령된곳이면 그건 true로 표시 
                flag=True
                return 
                



T=int(input())
for tc in range(1,T+1):
    N=int(input())
    visited = [[False]*N for _ in range(N)]
    flag=False
    total=0

    print(f'#{tc} {dfs(N)}')
'''
#쭉 전부다 안보고 그냥 한칸씩만 보고 true 준다음 다음 dfs 할때 조건 만족안하면 그냥 백트레킹 해버리는 방법
def dfs(i): #현재 퀸을 놓을 행번호
    global total

    if i==N: #마지막 행까지 퀸 다놓았으면 해결됨
        total+=1 # 퀸 다 놓은 경우의 수 1개 추가
        return
    
    for j in range(N): #열을 기준으로
        if not v1[j] and not v2[i+j] and not v3[i-j]:

            v1[j]=v2[i+j]=v3[i-j]=True

            dfs(i+1) #다음 행으로 이동 퀸 놓기 근데 그렇게 하고 만약에 퀸 모든 행에 다 놓으면 return하니까 그때 표시해놨던거 백트레킹
            #dfs 기점으로 전부다 열 기준으로 다시 보게됨 열 전체 탐색 여러가지 경우가 또 거기서 파생되서 뿌리가 내려감 근데 동시에 내려가다가 다른 자식 노드들은 
            #표시로 방해받으면 안되니까 백트레킹 해주는거 
            v1[j]=v2[i+j]=v3[i-j]=False






T=int(input())
for tc in range(1,T+1):
    N=int(input())
    total=0

    v1 = [False]*N #같은 열 체크
    v2 = [False]*(2*N) #우상향 체크
    v3 = [False]*(2*N) #우하향 체크

    dfs(0)

    print(f'#{tc} {total}')

