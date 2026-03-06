"""
📍 [BOJ] 1238 파티
> [학습 우선순위: Step 5 - 그래프/다익스트라응용]
> 모든 마을에서 X번 마을로 모였다가 다시 자기 집으로 돌아오는 왕복 시간 중 최댓값을 구하라.

🔍 상세 분석:
- **"가는 길"**과 **"오는 길"**을 구해야 합니다. 도로는 단방향입니다.
- **오는 길**: X번에서 출발해 모든 노드로 가는 다익스트라 1번.
- **가는 길**: 모든 노드에서 X로 가야 하는데, 노드마다 다익스트라를 돌리면 너무 느립니다.
- **트릭**: 간선의 방향을 전부 뒤집은 뒤(`reverse_graph`), X에서 다익스트라를 한 번 더 돌리면 "X로 들어오는 모든 경로"를 한 방에 구할 수 있습니다!

🏗️ 구현 체크리스트:
1. 정방향 그래프(`graph`)와 역방향 그래프(`reverse_graph`) 두 개를 만든다.
2. 정방향 다익스트라(X에서 출발) -> 각자의 집으로 돌아오는 시간.
3. 역방향 다익스트라(X에서 출발) -> 각자의 집에서 파티로 오는 시간.
4. 두 결과의 합 중 최댓값을 찾는다.

💡 학생 가이드:
- "방향을 왜 뒤집나요?" 
  -> A->X 의 최단 거리는 화살표를 뒤집었을 때 X->A 와 같기 때문입니다. 이 테크닉은 코딩 테스트에서 정말 유용하게 쓰이니 꼭 외워두세요!
"""

import heapq
import sys
input = sys.stdin.readline
INF = int(1e9)

def dijkstra(n, start, graph):
    """특정 시작점에서 모든 노드로의 최단 거리를 반환하는 함수"""
    distances = [INF] * (n + 1)
    distances[start] = 0
    q = [(0, start)]
    
    while q:
        dist, now = heapq.heappop(q)
        if distances[now] < dist:
            continue
        for next_node, weight in graph[now]:
            cost = dist + weight
            if cost < distances[next_node]:
                distances[next_node] = cost
                heapq.heappush(q, (cost, next_node))
    return distances

def solve():
    # N: 학생 수, M: 도로 수, X: 파티 장소
    N, M, X = map(int, input().split())
    
    # 1. 정방향과 역방향 그래프를 각각 생성
    graph = [[] for _ in range(N + 1)]
    reverse_graph = [[] for _ in range(N + 1)]
    
    for _ in range(M):
        u, v, w = map(int, input().split())
        graph[u].append((v, w)) # 정방향: u -> v
        reverse_graph[v].append((u, w)) # 역방향: v -> u (뒤집기!)
        
    # 2. X에서 각자의 집으로 가는 시간 (정방향 다익스트라)
    back_home = dijkstra(N, X, graph)
    # 3. 각자의 집에서 X로 오는 시간 (역방향 다익스트라 1번으로 해결!)
    go_party = dijkstra(N, X, reverse_graph)
    
    # 4. 왕복 시간(오고 가고)의 합 중 최댓값 찾기
    ans = 0
    for i in range(1, N + 1):
        ans = max(ans, go_party[i] + back_home[i])
            
    print(ans)

if __name__ == "__main__":
    solve()
