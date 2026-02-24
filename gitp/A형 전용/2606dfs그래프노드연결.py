'''
트리 형식의 트리 재귀 문제 
'''

n = int(input())
m = int(input())
graph = [[] for _ in range(n+1)] #그래프에서의 핵심 
for pair in range(m):
    a,b = map(int,input().split())
    graph[a].append(b) #그래프 이어주기 
    graph[b].append(a)
visited = [False]*(n+1) #dfs의 핵심인 백트레킹 재귀와 한몸 1번부터 n번이라고 하였으므로 n+1이됨
count=0

def dfs(start):
    global count
    visited[start]=True #백트레킹 표시

    for next_node in graph[start]: #다음 노드 판단
        if not visited[next_node]: #백트레킹한 부분에 false면 아직 방문 안해서 방문한다는 것 
            count+=1
            dfs(next_node) #리턴은 필요없음 그 컴퓨터로 이동하면 카운트 되므로 
        
dfs(1)
print(count)
