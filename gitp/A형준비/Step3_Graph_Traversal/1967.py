"""
📍 [BOJ] 1967 트리의 지름
> [학습 우선순위: Step 3 - 트리/최단거리]
> 가중치가 있는 트리에서 가장 멀리 떨어진 두 노드 사이의 거리를 구하라.

🔍 상세 분석:
- 트리의 신기한 성질 하나를 이용합니다.
- **"어떤 노드에서든 가장 먼 노드는, 전체 지름의 한쪽 끝점이다!"**
- 따라서 두 번의 탐색으로 지름을 구할 수 있습니다:
  1. 아무 노드(보통 1번)에서 가장 먼 노드 `A`를 찾는다. (이게 지름의 한쪽 끝!)
  2. 노드 `A`에서 가장 먼 노드 `B`를 찾는다. 
  3. `A`와 `B` 사이의 거리가 곧 지름이다.

🏗️ 구현 체크리스트:
1. 인접 리스트에 `(노드, 가중치)`를 저장한다.
2. `dfs` 함수로 노드 간 거리를 계산한다.
3. 첫 번째 DFS로 가장 먼 노드 번호를 얻는다.
4. 그 노드에서 다시 DFS를 돌려 최대 거리를 구한다.

💡 학생 가이드:
- "가중치가 있는데 BFS를 써도 되나요?" 
  -> 트리에서는 두 노드 사이의 경로가 유일합니다! 따라서 BFS든 DFS든 상관없이 끝까지 가면 그게 최단이자 최장 경로입니다. 여기서는 DFS가 구현이 좀 더 간단합니다.
"""

import sys
# 재귀 한도 확장 (노드가 1만 개이므로 필수)
sys.setrecursionlimit(20000)
input = sys.stdin.readline

def solve():
    n = int(input())
    # 노드가 1개면 지름은 0
    if n == 1:
        print(0)
        return
        
    # 1. 인접 리스트 생성 (연결 정보와 가중치 w 저장)
    adj = [[] for _ in range(n + 1)]
    for _ in range(n - 1):
        u, v, w = map(int, input().split())
        adj[u].append((v, w))
        adj[v].append((u, w))
        
    def dfs(node, current_dist, visited):
        """현재 노드에서 갈 수 있는 모든 곳의 거리를 기록하는 함수"""
        visited[node] = current_dist # 현재까지 온 거리 기록
        
        for next_node, weight in adj[node]:
            if visited[next_node] == -1: # 아직 안 가본 곳이면
                dfs(next_node, current_dist + weight, visited)

    # [Step 1] 1번 노드에서 가장 멀리 있는 노드 A 찾기
    visited1 = [-1] * (n + 1)
    dfs(1, 0, visited1)
    
    # 기록된 거리 중 최댓값을 가진 인덱스(노드 번호)가 A
    max_d1 = -1
    node_A = 1
    for i in range(1, n + 1):
        if visited1[i] > max_d1:
            max_d1 = visited1[i]
            node_A = i
    
    # [Step 2] 끝점 A에서 가장 멀리 있는 노드 B 찾기
    visited2 = [-1] * (n + 1)
    dfs(node_A, 0, visited2)
    
    # 기록된 거리 중 최댓값이 바로 트리의 지름!
    print(max(visited2))

if __name__ == "__main__":
    solve()
