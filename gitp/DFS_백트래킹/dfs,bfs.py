from collections import deque

def dfs(node,visited):
    visited[node]=True
    print(node, end=" ")

    for next_node in graph[node]:
        if not visited[next_node]:
            dfs(next_node,visited)

def bfs(start):
    
    visited=[False]*(N+1)
    queue=deque([start])
    visited[start]=True

    while queue:
        node = queue.popleft()
        print(node,end=" ")
        for next_node in graph[node]:
            if not visited[next_node]:
                visited[next_node]=True
                queue.append(next_node)



N,M,V = map(int,input().split())
graph=[[] for _ in range(N+1)]

for _ in range(M):
    a,b= map(int,input().split())
    graph[a].append(b)
    graph[b].append(a)


for i in range(1,N+1):
    graph[i].sort()

visited_dfs = [False]*(N+1)
dfs(V,visited_dfs) #dfs는 visited 배열을 밖에서 만들어줘야함 재귀해서 안에서 만들면 재귀때마다 초기화
#반면 bfs는 안에서 만들어도 어짜피 while문 안에서만 도니까 상관x 
print()
bfs(V)

