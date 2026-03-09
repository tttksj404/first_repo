def dfs(i,j,total):
    global min_sum

    if total>=min_sum: #다 봤는데 토탈값이 MIN보다 크면 그건 볼 필요가 없어서 그쪽 가지는 잘라주는거 끝까지 가기전 조건 안맞아서 끝으로 표시해준거  
        return #여긴 가지치기임 
    

    if i ==N-1 and j==N-1: #기저 조건 즉 끝까지 목적지 오른쪽 끝 갔을때를 의미 
        if min_sum>total:
            min_sum=total
        return #여긴 애초에 끝까지 가서 갱신하고 끝을 표시해주는거 
    
    for a in range(2):
        nr=i+dr[a]
        nc=j+dc[a]

        if 0<=nr<N and 0<=nc<N:
            if visited[nr][nc]==False:
                visited[nr][nc]=True
                dfs(nr,nc,total+picture[nr][nc]) #백트레킹은 그 지점부터 전부다 다시 탐색해본다는거 
                visited[nr][nc]=False #이건 가지중에 하나일뿐 이게 도달하더라도 다른 것도 살펴봐야해서 false줌 

   
    

    




dr=[0,1]
dc=[1,0]
T= int(input())
for tc in range(1,T+1):
    N=int(input())
    picture=[list(map(int,input().split())) for _ in range(N)]
    visited= [[False]*N for _ in range(N)]
    min_sum=9999999
    si,sj=0,0
    '''
사실 여긴 이렇게 시작점 탐색할 필요가 없음  문제 잘 읽어보면 맨 왼쪽 위에서 출발한다고 되어있음 문제 잘 읽기
    for j in range(N):
        if visited[0][j]==False:
            visited[0][j]=True
            si,sj=0,j
            dfs(si,sj,picture[0][j])
            visited[0][j]=False #경우의 수 따져주는 부분은 반드시 백트레킹 생각해보기 
    '''
    dfs(si,sj,picture[0][0])


    print(f'#{tc} {min_sum}')