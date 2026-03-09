'''
N이 뭐인지에 따라서 좌표값이 연결되는 방식이 다름 

'''
def dfs(current, count,battery_sum):
    global min_battery

    if battery_sum>min_battery:
        return
    
    if count==N-1:
        total= battery_sum+area[current][0]
        
        if total<min_battery:
            min_battery=total
        return
    for next_node in range(1,N):
        if not visited[next_node]:
            visited[next_node]=True
            dfs(next_node,count+1,battery_sum+area[current][next_node])
            visited[next_node]=False






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
