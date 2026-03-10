'''
N이 뭐인지에 따라서 좌표값이 연결되는 방식이 다름 

'''
def dfs(current, count,battery_sum):
    global min_battery

    if battery_sum>min_battery: #초반부 가지치기 해줄 대상 다 더한 배터리 합이 min보다 크면 애초에 더볼 필요없는 가지
        return
    
    if count==N-1: #카운트 끝까지 했을경우 기저 조건 맵에서 0부터 시작이 아닌 1부터 시작이라서
        total= battery_sum+area[current][0] #토탈값 지금까지의 베터리합에 끝에 있는 위치의 값 더해줌 
        
        if total<min_battery: 
            min_battery=total #여긴 이미 끝까지 간 상태의 가지에서 최솟값 갱신해서 돌아가서 다른거 하면됨
        return
    for next_node in range(1,N): #N=3 일때 처음 노드가 1이지만 실제 인덱스는 0 다음 노드는 당연히 2 아니면 3인데 이거 전부 인덱스로는 1,2이므로 가능
        if not visited[next_node]:
            visited[next_node]=True
            dfs(next_node,count+1,battery_sum+area[current][next_node])# dfs 할때 next_node로 한칸 간거니까 count+1 해주고, 배터리 이전까지 더해준 값에 지금 값까지 더해줌
            visited[next_node]=False #만약에 돌아오게 되면 그건 조건이 안맞는 가지이거나, 조건 달성해서 종료된 가지로서 다른 가지를 봐야하기에 백트레킹






T= int(input())
for tc in range(1,T+1):
    N=int(input())
    area=[list(map(int,input().split())) for _ in range(N)]
    # N에 따라서 
    # N=3 -> 1-2-3-1 / 1-3-2-1 2경우 
    # N=4 -> 1-2-3-4-1 /1-2-4-3-1 / 1-3-2-4-1 / 1-3-4-2-1 / 1-4-2-3-1/ 1-4-3-2-1 6경우
    # N=5 -> 

    min_battery = 999999
    visited = [False]*N

    visited[0]=True
    dfs(0,0,0)

    print(f'#{tc} {min_battery}')
