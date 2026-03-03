"""
📍 [BOJ] 1916 최소비용 구하기
> [학습 우선순위: Step 5 - 그래프/다익스트라]
> A도시에서 B도시까지 가는 최소 비용을 구하라.

🔍 상세 분석:
- 1753번과 거의 똑같은 다익스트라 문제입니다. 
- 차이점은 '모든 노드'가 아니라 '특정 도착지'까지의 비용만 출력하면 된다는 점입니다.

🏗️ 구현 체크리스트:
1. `heapq`를 활용한 다익스트라 기본 구조.
2. 도착 도시의 `distance[end_city]` 만 마지막에 출력.

💡 학생 가이드:
- "도시 번호가 1번부터 시작하나요?" 
  -> 네, 보통 그래프 문제는 1번부터 시작하므로 리스트 크기를 `N+1`로 잡는 게 안전합니다.
"""

import heapq
import sys
input = sys.stdin.readline
INF = int(1e9)

def dijkstra():
    N = int(input())
    M = int(input())
    
    graph = [[] for _ in range(N + 1)]
    for _ in range(M):
        u, v, w = map(int, input().split())
        graph[u].append((v, w))
        
    start_city, end_city = map(int, input().split())
    
    # 최단 거리 테이블
    distance = [INF] * (N + 1)
    
    # 힙 생성
    q = []
    heapq.heappush(q, (0, start_city))
    distance[start_city] = 0
    
    while q:
        dist, now = heapq.heappop(q)
        
        # 이미 처리된 노드 무시
        if distance[now] < dist:
            continue
            
        for next_node, weight in graph[now]:
            cost = dist + weight
            if cost < distance[next_node]:
                distance[next_node] = cost
                heapq.heappush(q, (cost, next_node))
                
    # 도착 도시까지의 최소 비용만 출력
    print(distance[end_city])

if __name__ == "__main__":
    dijkstra()
