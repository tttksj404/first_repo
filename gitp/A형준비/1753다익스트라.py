'''
V,E=map(int,input().split())
K=int(input()) #스타트 노드 값 
graph=[[] for _ in range(V+1)] #노드가 1부터 시작하므로
storage=[]
for _ in range(E):
    u,v,w = map(int,input().split())
    graph[u].append((v,w))
    graph[v].append((u,w))

    def dfs(node,current_dist,visited):
        visited[node]=current_dist
        storage.append(node)

        for next_node, weight in graph[node]:
            if visited[next_node]==-1:
                storage.append(next_node)
                dfs(next_node,current_dist+weight,visited)

visited1=[-1]*(V+1)
dfs(K,0,visited1)
storage=list(set(storage))

'''
import heapq

V,E=map(int,input().split())
K=int(input()) #스타트 노드 값 
INF = 1e8
graph=[[] for _ in range(V+1)] #노드가 1부터 시작하므로
for _ in range(E):
    u,v,w = map(int,input().split())
    graph[u].append((v,w)) #여기서 바꿔서는 안넣어도됨 그냥 다익스트라는 한방향



dist = [INF]*(V+1) #다익스트라에서 반드시 해줘야하는거 

def dji(start):
    q = []
    heapq.heappush(q,(0,start)) #힙에다가 초기 값 넣어주기 
    dist[start]=0 #dist 값 초기값 초기화 

    while q:
        distance,now = heapq.heappop(q) #넣은 값 뽑아오기 

        if dist[now]<distance: #힙에서 밀려났는데 처리순위 후순위 / 시간줄이는 수단 반드시 할 필요x
            continue

        for next_node in graph[now]:
            if distance+next_node[1]<dist[next_node[0]]:
                dist[next_node[0]]= distance+next_node[1]
                heapq.heappush(q,(distance+next_node[1],next_node[0]))


dji(K)
#1번 정점부터 V번 정점까지 결과 출력 
for i in range(1, V + 1):
    if dist[i] == INF:
        print("INF")
    else:
        print(dist[i])
    


