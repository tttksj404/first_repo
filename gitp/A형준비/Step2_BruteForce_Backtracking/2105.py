'''

(대각선 오른쪽 위- 대각선 왼쪽 아래 / 대각선 오른쪽 아래 - 대각선 왼쪽 위  ) 이렇게 개수가 같게 묶여야함
무조건 시작점에서 대각선 오른쪽 위로 가야하고 더 가도 되지만 대각선 왼쪽 아래 수가 이거에 맞아야함
4.대각선 오른쪽 위 (-1,+1) RU
1. 대각선 오른쪽 아래  (+1,+1) RD
pair
2. 대각선 왼쪽 아래 (+1,-1) LD
3. 대각선 왼쪽 위 (-1,-1) LU
그래서 결국 시작점으로 돌아와야만 함

근데 조건은 대각선 타고 탐색하면서 모든 값을 저장해놓고 그게 탐색할때 같은 수가 하나라도 등장하면 그 루프는 볼필요 없음
바로 다른거 봐야함
visited를 주고 그거에 대해 백트레킹 하면서 다른 시작점 봐주기
'''
#0:RD , 1:LD , 2:LU , 3:RU
di = [1,1,-1,-1]
dj= [1,-1,-1,1]

def dfs(i,j,d, path):
    global max_desserts,si,sj

    for next_d in range(d,d+2): #이 로직이 결국 d를 그대로 나갈꺼냐 아니면 하나만 방향전환할꺼냐고 가능함!!
        if next_d>3: #방향이 다 바뀌었으면 더 커지지 말고 끝내야함
            break

        ni,nj= i+di[next_d],j+dj[next_d]

        #다음 위치가 시작점이라면? 루프 완성!
        # 사각형이 되려면 최소한 3번 방향(RU)까지는 도달했어야 함
        if ni==si and nj==sj:
            if next_d>2:
                max_desserts = max(max_desserts, len(path))
                return # 루프 완성했으므로 해당 경로 종료


        if 0<=ni<N and 0<=nj<N:
            if cafe[ni][nj] not in path:
                path.add(cafe[ni][nj])
                dfs(ni,nj,next_d,path)
                path.remove(cafe[ni][nj])









T= int(input())
for tc in range(1,T+1):
    N=int(input())
    cafe = [list(map(int, input().split())) for _ in range(N)]
    si,sj=0,0
    max_desserts =-1
    for i in range(N):
        for j in range(N):
            if  j==0 or i==N or j==N or i==N-1:
                pass
            else:
                si,sj=i,j
                dfs(i,j,0,{cafe[i][j]}) #set()넣는 이유는 어짜피 path에는 중복값만 있는지 확인만 하면되니까 그냥 list넣으면 그 중복값 있는지 다시 연산필요

    print(f'#{tc} {max_desserts}')
