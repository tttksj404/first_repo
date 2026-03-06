"""
📍 [BOJ] 14567 선수과목 (Prerequisite)
> [학습 우선순위: Step 5 - 그래프/위상정렬]
> 선수과목 조건이 있을 때, 각 과목을 몇 학기에 들을 수 있는지 구하라.

🔍 상세 분석:
- 2252번과 동일한 위상 정렬입니다. 
- 추가된 점은 **"학기 수(계층)"**를 기록해야 한다는 것입니다.
- 어떤 과목을 듣는 학기는 **(선수과목 이수 학기 + 1)** 이 됩니다.

🏗️ 구현 체크리스트:
1. 위상 정렬 기본 구조를 유지한다.
2. `result` 배열에 각 과목의 학기를 저장한다 (초기값은 모두 1학기).
3. 큐에서 뺀 `curr` 과목과 연결된 `next` 과목에 대해:
   - `result[next] = result[curr] + 1`

💡 학생 가이드:
- "한 학기에 여러 과목을 들어도 되나요?" 
  -> 네, 선수과목 조건만 맞으면 됩니다. 그래서 위상 정렬 큐에 들어있는 노드들은 동시에 처리되는 계층이라고 생각하면 이해가 빠릅니다.
"""

from collections import deque
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
        
    # ans[i]는 i번 과목을 이수할 수 있는 최소 학기
    ans = [1] * (N + 1)
    q = deque()
    
    for i in range(1, N + 1):
        if indegree[i] == 0:
            q.append(i)
            
    while q:
        curr = q.popleft()
        for next_node in adj[curr]:
            indegree[next_node] -= 1
            if indegree[next_node] == 0:
                # 선수과목을 끝낸 학기 바로 다음 학기에 수강!
                ans[next_node] = ans[curr] + 1
                q.append(next_node)
                
    print(*(ans[1:]))

if __name__ == "__main__":
    solve()
