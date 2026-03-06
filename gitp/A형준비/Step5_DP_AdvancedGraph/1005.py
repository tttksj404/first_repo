"""
📍 [BOJ] 1005 ACM Craft
> [학습 우선순위: Step 5 - 그래프/위상정렬+DP]
> 건물을 짓기 위한 선후 관계와 소요 시간이 주어질 때, 목표 건물을 짓는 최소 시간을 구하라.

🔍 상세 분석:
- 위상 정렬에 **동적 계획법(DP)**이 섞인 고난도 문제입니다.
- 어떤 건물을 짓기 시작할 수 있는 시간은, 그 건물을 짓기 위해 필요한 **모든 선수 건물들 중 가장 늦게 끝나는 건물의 시간**입니다.
- `dp[건물] = max(선수건물들의 종료시간) + 현재건물 소요시간`

🏗️ 구현 체크리스트:
1. 위상 정렬 큐를 사용한다.
2. `dp` 배열을 `build_time`으로 초기화한다. (진입 차수 0인 것들은 본인 시간 그대로)
3. 큐에서 뺀 `curr` 건물이 끝나면, 연결된 `next` 건물의 `dp`를 `max`로 갱신한다.
4. 테스트 케이스가 여러 개이므로 매번 초기화를 잘 해야 한다.

💡 학생 가이드:
- "왜 max를 쓰나요?" 
  -> 건물을 동시에 지을 수 있다고 했으므로, 여러 선수 건물 중 가장 오래 걸리는 녀석이 끝나야만 다음 건물을 시작할 수 있기 때문입니다.
"""

from collections import deque
import sys
input = sys.stdin.readline

def solve():
    T = int(input())
    for _ in range(T):
        N, K = map(int, input().split())
        times = [0] + list(map(int, input().split())) # 각 건물 소요 시간
        adj = [[] for _ in range(N + 1)]
        indegree = [0] * (N + 1)
        
        for _ in range(K):
            u, v = map(int, input().split())
            adj[u].append(v)
            indegree[v] += 1
            
        W = int(input()) # 최종 지어야 할 건물 번호
        
        # dp[i]는 i번 건물을 다 짓는 데까지 걸리는 총 시간 (선수 건물 포함)
        dp = [0] * (N + 1)
        q = deque()
        
        # 1. 진입 차수 0인 노드부터 큐에 넣고 DP 초기값 설정
        for i in range(1, N + 1):
            if indegree[i] == 0:
                q.append(i)
                dp[i] = times[i]
                
        # 2. 위상 정렬 시작
        while q:
            curr = q.popleft()
            
            # 연결된 다음 건물들 확인
            for next_node in adj[curr]:
                # 다음 건물의 시작 가능 시간은 선수 건물들 중 최대값으로 결정!
                dp[next_node] = max(dp[next_node], dp[curr] + times[next_node])
                indegree[next_node] -= 1
                if indegree[next_node] == 0:
                    q.append(next_node)
                    
        print(dp[W])

if __name__ == "__main__":
    solve()
