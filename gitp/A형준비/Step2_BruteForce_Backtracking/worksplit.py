'''
1부터 N 
직원번호 i 
일 번호 j 

첫줄에는 1번 직원이 일 1,2,3을 했을때 성공확률 13, 0 ,50 
 2번 직원 12,70,90
 3번 직원 25,60,100 

 1.경우의 수 전부다 따져줘야하는데 이걸 가지치기로 가능 max 확률보다 다 곱했을때 확률이 작으면 그건 필요x 
 2.기저 조건은 일 배분이 다 이뤄졌을때 return
 3. 일단 일감을 리스트에다가 담아두고 그걸 pop append로 백트레킹하기 


'''
def dfs(worker_idx,sum_percentage): #이런식으로 ind가 두가지 이상 쓰여야할때 주의 하기 한쪽만 패러메터로 잡아주고 하나는 이동시켜주며 변경
    global max_percentage
    
    if sum_percentage<max_percentage:
        return
    
    if worker_idx==N:
        if sum_percentage>max_percentage:
            max_percentage=sum_percentage
            return
        
    for job_idx in range(N): #한쪽은 dfs패러매터로 +1씩 해서 조절하고 다른 인덱스만 for로 조절해주기 
        if not visited[job_idx]:
            if chance[worker_idx][job_idx]==0:
                continue #조건에 따라 continue달아서 처리 이 아래는 보지도 않는다 0%면 어짜피 어떤 수 곱하든 최소값이라서
            
            visited[job_idx]=True
            dfs(worker_idx+1,sum_percentage*(chance[worker_idx][job_idx]/100))
            visited[job_idx]=False


T=int(input())
for tc in range(1,T+1):
    N=int(input())
    chance = [list(map(int,input().split())) for _ in range(N)]
    # chance[0][0] 이건 1번 사람이 1번 일을 맡았을때 i=사람번호 , j=일번호

    visited = [False]*N  #해야될 일감 

    max_percentage=0

    dfs(0,1.0)

    print(f'#{tc} {max_percentage * 100:.6f}')