import sys
from collections import deque

# 재귀 한도 설정 (DFS를 위해)
sys.setrecursionlimit(10**6)
input = sys.stdin.readline

# N: 정점 개수, M: 간선 개수, V: 시작 정점
n, m, v = map(int, input().split())

# 인접 리스트로 그래프 구현
graph = [[] for _ in range(n + 1)] #[]를 다 찍어주기 

for _ in range(m):
    a, b = map(int, input().split())
    graph[a].append(b) #a의 인접값인 b 넣어주고 
    graph[b].append(a) #b의 인접값으로 당연히 a 넣어줌 이게 [a] [b...] / [b] [a.....]이런형식 

# "번호가 작은 것부터 방문"하기 위해 정렬 [][]순서에서 앞뒤 순서 정렬 ex)1 4 / 1 3 / 1 2  이면 [1] [4,3,2]나와서 이걸 sort로 [1] [2,3,4]
for i in range(1, n + 1):
    graph[i].sort()

# DFS 구현 (재귀)
def dfs(node, visited):
    visited[node] = True #재방문 막고자 하기 위해 메커니즘 시작전 제약조건인 true 걸어두고 시작 
    #그냥 visited는 true false로 이뤄져서 인덱스 찾고 그 값은 true, false임 / bfs에서 visited를 정의했는데 만약 dfs에서 정의하면 재귀로 계속 초기화 되기에
    print(node, end=' ')
    for next_node in graph[node]:
        if not visited[next_node]:
            dfs(next_node, visited)

# BFS 구현 (큐) #재귀 필요 x 이미 처음부터 제대로 넓게 탐색한다고 생각하기에 
def bfs(start):
    visited = [False] * (n + 1) #(n+1)의 이유 인덱스 번호 맞추려고 [false]라서 애초에 리스트 인덱스 생각 
    queue = deque([start]) #시작점 찍어주기 
    visited[start] = True #시작점은 방문 이력 남김 
    
    while queue:
        node = queue.popleft() #큐에서 왼쪽꺼 즉 처음 시작값은 버려야 초기화됨 그리고 방문했던 값도 버리고 그걸 프린트해야 방문 했다고 출력가능 
        print(node, end=' ')
        for next_node in graph[node]: #그래프에 담긴 값 즉 전체 범위내에서 다음 노드 탐색 
            if not visited[next_node]: #방문이력에 해당 다음 방문할 노드 없다면
                visited[next_node] = True #방문할꺼니까 방문이력 남기기 
                queue.append(next_node) #그리고 그 노드는 큐에 담기 

# 결과 출력
visited_dfs = [False] * (n + 1)
dfs(v, visited_dfs) #dfs탐색을 시작할 정점의 번호 v 
print() # 줄바꿈
bfs(v) #bfs탐색을 시작할 정점의 번호 v 
