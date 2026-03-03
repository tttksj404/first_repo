# Step 5: DP & 고급 그래프 마스터 가이드

이 단계의 목표는 문제에 숨겨진 점화식을 찾아내고, 복잡한 노드 관계를 효율적으로 처리하는 고급 알고리즘을 익히는 것입니다.

### 1. DP 점화식을 세우는 사고법

DP는 "큰 문제를 작은 문제로 쪼개고, 작은 문제의 답을 기록해 재활용한다"는 원리입니다.

1.  **DP 테이블 정의**: `dp[i]`가 무엇을 의미하는지 명확히 정의한다.
    - 예: `dp[i]` = i를 1로 만드는 최소 횟수 (1463번)
    - 예: `dp[i]` = i번째 숫자를 포함하는 최대 연속합 (1912번)
2.  **초기값 설정**: `dp[0]`이나 `dp[1]` 등 가장 작은 문제의 답을 손으로 직접 구해서 넣는다.
3.  **점화식 도출**: `dp[i]`와 `dp[i-1]`, `dp[i-2]` 등 이전 값들과의 관계를 찾는다.
    - "i번째 계단을 오르는 방법은, i-1에서 오거나 i-2에서 오는 것뿐이다." -> `dp[i] = dp[i-1] + dp[i-2]`

### 2. 다익스트라(Dijkstra) 알고리즘 템플릿

- **언제?**: **가중치가 있는 그래프**에서 한 노드로부터 다른 모든 노드까지의 **최단 거리**를 구할 때.
- **핵심**: 우선순위 큐(`heapq`)를 사용해 '가장 가까운 노드'부터 방문한다.

```python
import heapq
INF = int(1e9)

# 1. 그래프, 거리 테이블, 힙 준비
graph = [[] for _ in range(N+1)]
distance = [INF] * (N+1)
pq = []

# 2. 시작점 설정
distance[start] = 0
heapq.heappush(pq, (0, start)) # (거리, 노드) 순서

while pq:
    dist, now = heapq.heappop(pq)
    
    if distance[now] < dist: continue # 이미 처리된 노드

    for next_node, weight in graph[now]:
        cost = dist + weight
        if cost < distance[next_node]:
            distance[next_node] = cost
            heapq.heappush(pq, (cost, next_node))
```

### 3. 위상 정렬(Topology Sort) 템플릿

- **언제?**: **선후 관계(순서)**가 정해진 작업들을 순서대로 나열할 때.
- **핵심**: 진입 차수(Indegree)가 0인 노드(선행 작업이 없는 노드)부터 큐에 넣고 처리한다.

```python
from collections import deque

# 1. 인접 리스트, 진입 차수 배열 준비
adj = [[] for _ in range(N+1)]
indegree = [0] * (N+1)
# ... 간선 정보 입력 및 indegree 카운트 ...

# 2. 진입 차수 0인 노드 큐에 삽입
q = deque()
for i in range(1, N+1):
    if indegree[i] == 0:
        q.append(i)

while q:
    curr = q.popleft()
    # ... 정답 처리 ...
    for next_node in adj[curr]:
        indegree[next_node] -= 1
        if indegree[next_node] == 0:
            q.append(next_node)
```
- **사이클 판별**: 정렬이 끝났는데 결과 리스트의 길이가 N보다 작으면 사이클이 존재함. (2623번)
- **우선순위 부여**: `deque` 대신 `heapq`를 쓰면 특정 조건(번호가 작은 순 등)을 추가할 수 있음. (1766번)
