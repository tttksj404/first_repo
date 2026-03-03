"""
📍 [BOJ] 11725 트리의 부모 찾기
> [학습 우선순위: Step 3 - 트리/BFS]
> 루트가 1인 트리에서 각 노드의 부모를 구하는 프로그램.

🔍 상세 분석:
- 트리는 루트가 정해지면 '위-아래' 관계가 생깁니다.
- 1번(루트)에서 출발해 밑으로 내려가면, 먼저 방문한 노드가 무조건 '부모'가 됩니다.
- BFS를 돌리면서 `parent[자식] = 부모`를 계속 기록하면 끝입니다.

🏗️ 구현 체크리스트:
1. 인접 리스트로 트리 그래프를 저장한다. (양방향 연결)
2. `parent` 배열을 만들어 부모 정보를 저장한다. (0으로 초기화하면 방문 체크 겸용 가능)
3. 1번 노드부터 BFS 시작.
4. 다음 노드가 아직 부모가 없다면(`0`이라면), 현재 노드가 그 녀석의 부모다!

💡 학생 가이드:
- "왜 루트 1부터 시작해야 하나요?" 
  -> 문제에서 1번을 루트라고 정해줬기 때문입니다. 탐색의 출발지가 계급의 최상위층이 되는 원리죠!
"""

from collections import deque
import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    # 1. 인접 리스트 생성 (양방향 연결)
    adj = [[] for _ in range(N + 1)]
    for _ in range(N - 1):
        u, v = map(int, input().split())
        adj[u].append(v)
        adj[v].append(u)
        
    # 2. 부모 정보 저장 리스트 (0이면 아직 방문 안 함을 의미)
    parent = [0] * (N + 1)
    
    # 3. BFS 시작 (루트 1번부터)
    queue = deque([1])
    parent[1] = 1 # 루트는 편의상 1(자기자신)로 표시해서 방문 처리
    
    while queue:
        curr = queue.popleft()
        
        for neighbor in adj[curr]:
            # 만약 연결된 노드가 아직 부모가 정해지지 않았다면?
            if parent[neighbor] == 0:
                # 지금 내가(curr) 너의 부모다!
                parent[neighbor] = curr
                queue.append(neighbor) # 자식 노드를 다음 탐색지로
                
    # 4. 2번 노드부터 부모 출력
    for i in range(2, N + 1):
        print(parent[i])

if __name__ == "__main__":
    solve()
