"""
📍 [BOJ] 2252 줄 세우기
> [학습 우선순위: Step 5 - 그래프/위상정렬]
> 키 비교 결과가 주어졌을 때, 학생들을 순서대로 세우는 프로그램을 작성하라.

🔍 상세 분석:
- **위상 정렬(Topology Sort)**의 정석 문제입니다. 
- 선후 관계(누가 누구보다 앞에 서야 함)가 있을 때, 그 관계를 깨지 않고 일렬로 세우는 방법입니다.
- **진입 차수(In-degree)**가 0인 노드(나보다 앞에 서야 할 사람이 없는 사람)부터 큐에 넣고 처리합니다.

🏗️ 구현 체크리스트:
1. 각 노드의 진입 차수(`indegree`)를 기록한다.
2. 진입 차수가 0인 모든 노드를 큐에 넣는다.
3. 큐에서 노드를 꺼내고, 그 노드와 연결된(내 뒤에 서야 할) 사람들의 진입 차수를 1씩 깎는다.
4. 깎다가 0이 된 사람이 있으면 큐에 넣는다.

💡 학생 가이드:
- "순서가 여러 개 나올 수 있나요?" 
  -> 네, 위상 정렬은 정답이 유일하지 않을 수 있습니다. 문제에서도 가능한 아무거나 하나 출력하라고 했으므로 큐에 먼저 들어가는 순서대로 뽑아내면 됩니다.
"""

from collections import deque
import sys
input = sys.stdin.readline

def solve():
    # N: 학생 수, M: 비교 횟수
    N, M = map(int, input().split())
    # 1. 인접 리스트와 진입 차수 장부 준비
    adj = [[] for _ in range(N + 1)]
    indegree = [0] * (N + 1)
    
    for _ in range(M):
        u, v = map(int, input().split())
        adj[u].append(v) # u가 v보다 앞에 서야 함
        indegree[v] += 1 # v는 앞에 서야 할 사람이 한 명 생김
        
    # 2. 진입 차수가 0인 사람(제일 앞에 설 수 있는 사람)들 찾기
    q = deque()
    for i in range(1, N + 1):
        if indegree[i] == 0:
            q.append(i)
            
    # 3. 위상 정렬 시작
    ans = []
    while q:
        curr = q.popleft()
        ans.append(curr) # 줄 세우기!
        
        # 현재 내 뒤에 서야 했던 사람들의 조건을 하나씩 해제
        for next_node in adj[curr]:
            indegree[next_node] -= 1
            # 이제 내 앞에 아무도 없다면?
            if indegree[next_node] == 0:
                q.append(next_node) # 큐에 넣어서 줄 세울 후보로 등록
                
    print(*ans)

if __name__ == "__main__":
    solve()
