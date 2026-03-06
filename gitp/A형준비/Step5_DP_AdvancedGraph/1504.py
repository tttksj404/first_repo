"""
📍 [BOJ] 1504 특정한 최단 경로
> [학습 우선순위: Step 5 - 그래프/다익스트라응용]
> 1번에서 N번으로 가는데, 반드시 정점 v1과 v2를 거쳐야 한다. 최단 거리를 구하라.

🔍 상세 분석:
- 경유지가 있는 최단 경로 문제입니다. 
- 가능한 시나리오는 두 가지입니다:
  1. `1 -> v1 -> v2 -> N`
  2. `1 -> v2 -> v1 -> N`
- 이 구간들의 최단 거리를 각각 구해서 합친 뒤 더 작은 값을 고르면 됩니다.
- 다익스트라를 총 세 곳(1, v1, v2)에서 각각 돌려야 합니다.

🏗️ 구현 체크리스트:
1. 다익스트라 함수를 구현한다.
2. 1번 기점, v1 기점, v2 기점 다익스트라 결과를 각각 얻는다.
3. 시나리오 1: `dist1[v1] + dist_v1[v2] + dist_v2[N]`
4. 시나리오 2: `dist1[v2] + dist_v2[v1] + dist_v1[N]`
5. 둘 중 최솟값을 택하고, 경로가 없으면(INF) -1을 출력한다.

💡 학생 가이드:
- "간선이 무방향(양방향)인가요?" 
  -> 네, 문제에서 방향성이 없다고 했으므로 인접 리스트에 `u->v` 와 `v->u` 를 모두 넣어줘야 합니다.
"""

import heapq
import sys
input = sys.stdin.readline
INF = int(1e9)

def dijkstra(n, start, graph):
    dist = [INF] * (n + 1)
    dist[start] = 0
    q = [(0, start)]
    while q:
        d, now = heapq.heappop(q)
        if dist[now] < d: continue
        for next_node, weight in graph[now]:
            cost = d + weight
            if cost < dist[next_node]:
                dist[next_node] = cost
                heapq.heappush(q, (cost, next_node))
    return dist

def solve():
    N, E = map(int, input().split())
    # 양방향 그래프 구성
    graph = [[] for _ in range(N + 1)]
    for _ in range(E):
        u, v, w = map(int, input().split())
        graph[u].append((v, w))
        graph[v].append((u, w))
        
    v1, v2 = map(int, input().split())
    
    # 1, v1, v2 각각에서 다익스트라 돌리기
    from_1 = dijkstra(N, 1, graph)
    from_v1 = dijkstra(N, v1, graph)
    from_v2 = dijkstra(N, v2, graph)
    
    # 두 가지 필수 경로 합산
    path1 = from_1[v1] + from_v1[v2] + from_v2[N] # 1 -> v1 -> v2 -> N
    path2 = from_1[v2] + from_v2[v1] + from_v1[N] # 1 -> v2 -> v1 -> N
    
    res = min(path1, path2)
    
    # 경로가 존재하지 않는 경우 처리
    if res >= INF:
        print(-1)
    else:
        print(res)

if __name__ == "__main__":
    solve()
