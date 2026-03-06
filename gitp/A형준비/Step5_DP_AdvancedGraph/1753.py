"""
📍 [BOJ] 1753 최단경로
> [학습 우선순위: Step 5 - 그래프/다익스트라]
> 한 시작점에서 다른 모든 정점으로의 최단 경로를 구하라.

🔍 상세 분석:
- **다익스트라(Dijkstra)** 알고리즘의 표준입니다.
- 가중치가 있는 그래프에서 최단 거리를 구하며, **우선순위 큐(Heap)**를 써야 O(E log V)로 빠르게 끝납니다.
- "지금까지 발견된 가장 짧은 곳부터 방문한다"는 그리디한 원리를 따릅니다.

🏗️ 구현 체크리스트:
1. 인접 리스트로 그래프 정보를 저장한다.
2. `distance` 배열을 무한대(INF)로 초기화한다.
3. 시작 노드를 힙에 넣고 `distance[start] = 0` 설정.
4. 힙에서 꺼낸 거리 정보가 현재 기록된 거리보다 크면 무시한다. (이미 더 좋은 길을 찾았으므로)

💡 학생 가이드:
- "힙을 왜 쓰나요?" 
  -> 힙을 안 쓰면 매번 모든 노드를 뒤져서 최솟값을 찾아야 합니다(O(V^2)). 힙은 최솟값을 O(1)에 알려주기 때문에 훨씬 효율적입니다.
"""

import heapq
import sys
input = sys.stdin.readline
INF = int(1e9) # 무한대를 상징하는 아주 큰 수

def solve():
    # V: 정점 수, E: 간선 수
    V, E = map(int, input().split())
    # 시작 노드 K
    K = int(input())
    
    # 1. 인접 리스트 생성
    graph = [[] for _ in range(V + 1)]
    for _ in range(E):
        u, v, w = map(int, input().split())
        graph[u].append((v, w)) # u에서 v로 가는 가중치 w
        
    # 2. 최단 거리 테이블 초기화
    distance = [INF] * (V + 1)
    
    # 3. 우선순위 큐(최소 힙) 준비
    q = []
    # (거리 0, 시작노드 K) 튜플 삽입 (거리가 맨 앞이어야 거리순 정렬됨)
    heapq.heappush(q, (0, K))
    distance[K] = 0
    
    while q:
        # 현재 가장 짧은 거리에 있는 노드 정보를 꺼냄
        dist, now = heapq.heappop(q)
        
        # 만약 지금 꺼낸 거리가 이미 기록된 거리보다 크다면? 이미 처리된 노드이므로 무시!
        if distance[now] < dist:
            continue
            
        # 현재 노드와 연결된 다른 노드들을 확인
        for next_node, weight in graph[now]:
            cost = dist + weight
            # 지금 나를 거쳐서 다음 노드로 가는 게 더 빠르다면?
            if cost < distance[next_node]:
                distance[next_node] = cost
                heapq.heappush(q, (cost, next_node))
                
    # 4. 결과 출력
    for i in range(1, V + 1):
        if distance[i] == INF:
            print("INF")
        else:
            print(distance[i])

if __name__ == "__main__":
    solve()
