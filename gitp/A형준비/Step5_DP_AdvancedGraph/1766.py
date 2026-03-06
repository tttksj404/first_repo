"""
📍 [BOJ] 1766 문제집
> [학습 우선순위: Step 5 - 그래프/위상정렬+힙]
> 선후 관계가 있는 문제를 풀되, 가능한 번호가 작은(쉬운) 문제부터 풀어라.

🔍 상세 분석:
- 위상 정렬에서 **"우선순위"** 조건이 붙은 케이스입니다. 
- 진입 차수가 0인 노드들 중에서 **가장 번호가 작은 노드**를 먼저 꺼내야 합니다.
- 따라서 일반 큐(`deque`) 대신 **우선순위 큐(`heapq`)**를 사용합니다.

🏗️ 구현 체크리스트:
1. `heapq` 모듈을 사용한다.
2. 진입 차수가 0인 노드들을 힙에 넣는다.
3. `heappop`으로 가장 작은 번호를 꺼내 정답에 담고 위상 정렬을 이어간다.

💡 학생 가이드:
- "큐를 힙으로 바꾸기만 하면 되나요?" 
  -> 네! 위상 정렬의 기본 틀은 유지한 채, '누구를 먼저 꺼낼 것인가'라는 선택의 도구만 힙으로 교체하면 됩니다.
"""

import heapq
import sys
input = sys.stdin.readline

def solve():
    N, M = map(int, input().split())
    adj = [[] for _ in range(N + 1)]
    indegree = [0] * (N + 1)
    
    for _ in range(M):
        u, v = map(int, input().split())
        adj[u].append(v)
        indegree[v] += 1
        
    # [중요] 일반 큐 대신 최소 힙을 사용!
    # 그래야 진입 차수가 0인 노드 중 가장 작은 번호부터 나옴
    pq = []
    for i in range(1, N + 1):
        if indegree[i] == 0:
            heapq.heappush(pq, i)
            
    ans = []
    while pq:
        curr = heapq.heappop(pq)
        ans.append(curr)
        
        for next_node in adj[curr]:
            indegree[next_node] -= 1
            if indegree[next_node] == 0:
                heapq.heappush(pq, next_node)
                
    print(*ans)

if __name__ == "__main__":
    solve()
