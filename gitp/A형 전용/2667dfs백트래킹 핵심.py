'''
최단거리는 아님 
->dfs임 
'''
def dfs(a,b):
    global count    
    dr=[-1,1,0,0]
    dc=[0,0,-1,1]

    for idx in range(4):
        nr=a+dr[idx]
        nc=b+dc[idx]

        if 0<=nr<N and 0<=nc<N and town[nr][nc]==1 and visited[nr][nc]==False:
            count+=1
            visited[nr][nc]=True
            dfs(nr,nc)
            




storage=[]
N=int(input())
town = [list(map(int,input().strip())) for _ in range(N)]
visited = [[False]*N for _ in range(N)]
s_i,s_j=0,0
for i in range(N):
    for j in range(N):
        if town[i][j]==1 and visited[i][j]==False: #여기서 1찾는 것 뿐 아니라 visited도 조건 필요함
            s_i,s_j=i,j
            visited[s_i][s_j]=True
            count=1
            dfs(s_i,s_j)
            storage.append(count)
storage.sort()
print(len(storage))
for ind in range(len(storage)):
    print(storage[ind])

            











