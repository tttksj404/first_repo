"""
📍 [BOJ] 18352 특정 거리의 도시 찾기
> [학습 우선순위: Step 3 - BFS/최단거리]
> 가중치가 모두 1인 그래프에서 시작 도시 X로부터 최단 거리가 딱 K인 도시들을 구하라.

🔍 상세 분석:
- **"모든 도로의 거리가 1이다"** -> 무조건 BFS(너비 우선 탐색)가 정답입니다.
- BFS는 레벨(거리)별로 퍼져나가는 탐색이기 때문에, 가장 먼저 도착한 것이 곧 최단 거리입니다.
- `distance` 배열을 -1로 채워두고, 거리를 한 칸 갈 때마다 1씩 늘려가며 기록합니다.

🏗️ 구현 체크리스트:
1. 인접 리스트로 도시 연결 정보를 저장한다.
2. `distance` 리스트를 -1로 초기화한다 (X 도시만 0으로 시작).
3. 큐가 빌 때까지 다음 도시들을 탐색하며 `현재거리 + 1`을 기록한다.
4. 탐색이 끝나면 거리가 K인 도시 번호를 찾아 오름차순 출력한다.

💡 학생 가이드:
- "다익스트라(Dijkstra)와 무엇이 다른가요?" 
  -> 다익스트라는 도로마다 비용이 다를 때 쓰지만, 여긴 모두 1로 똑같습니다. 이럴 땐 일반 큐를 쓰는 BFS가 훨씬 빠르고 간편합니다!
"""

from collections import deque
import sys
input = sys.stdin.readline

def solve():
    # N: 도시 개수, M: 도로 개수, K: 목표 거리, X: 출발 도시
    N, M, K, X = map(int, input().split())
    # 1. 인접 리스트 생성 (단방향 도로)
    adj = [[] for _ in range(N + 1)]
    for _ in range(M):
        u, v = map(int, input().split())
        adj[u].append(v)
        
    # 2. 거리 기록 장부 (-1은 아직 안 가본 곳)
    dist = [-1] * (N + 1)
    dist[X] = 0 # 출발지는 거리가 0
    
    # 3. BFS 시작
    q = deque([X])
    while q:
        curr = q.popleft()
        
        # 현재 도시와 연결된 다음 도시들 확인
        for neighbor in adj[curr]:
            # 아직 방문하지 않은 도시라면?
            if dist[neighbor] == -1:
                # 지금 내 거리에서 +1 한 것이 저 도시의 최단 거리!
                dist[neighbor] = dist[curr] + 1
                q.append(neighbor)
                
    # 4. 결과 확인
    found = False
    for i in range(1, N + 1):
        if dist[i] == K:
            print(i)
            found = True
            
    # 거리가 K인 도시가 한 곳도 없다면 -1 출력
    if not found:
        print(-1)

if __name__ == "__main__":
    solve()
