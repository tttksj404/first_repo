"""
📍 [BOJ] 1647 도시 분할 계획
> [학습 우선순위: Step 5 - 그래프/최소신장트리]
> 전체 마을을 두 개로 분할하되, 각 마을 내부의 연결 유지비 합을 최소화하라.

🔍 상세 분석:
- **최소 신장 트리(MST)**를 활용하는 문제입니다.
- 모든 집을 연결하는 가장 싼 길들(MST)을 먼저 찾습니다.
- 그러면 집들은 하나의 거대한 마을이 됩니다. 여기서 **'가장 비싼 길 하나'**를 끊어버리면?
- 자연스럽게 마을이 두 개로 쪼개지면서, 각각의 마을 내부는 여전히 연결되어 있고 비용은 최소가 됩니다!

🏗️ 구현 체크리스트:
1. **크루스칼(Kruskal)** 알고리즘을 사용한다.
2. 모든 간선을 비용 순으로 오름차순 정렬한다.
3. 사이클이 생기지 않게 유니온-파인드(Union-Find)로 연결한다.
4. 마지막에 연결된 간선(가장 비싼 간선)을 총합에서 뺀다.

💡 학생 가이드:
- "왜 제일 비싼 걸 빼나요?" 
  -> MST를 구성하는 N-1개의 간선 중 하나를 빼면 반드시 두 덩어리로 나뉩니다. 이때 가장 비싼 걸 빼야 남은 비용의 합이 최소가 되기 때문입니다!
"""

import sys
input = sys.stdin.readline

def find_parent(parent, x):
    # 경로 압축: 루트 노드를 바로 찾도록 갱신
    if parent[x] != x:
        parent[x] = find_parent(parent, parent[x])
    return parent[x]

def union_parent(parent, a, b):
    # 두 집합을 합침
    a = find_parent(parent, a)
    b = find_parent(parent, b)
    if a < b: parent[b] = a
    else: parent[a] = b

def solve():
    N, M = map(int, input().split())
    
    # 1. 모든 간선 정보를 담고 비용 순으로 정렬
    edges = []
    for _ in range(M):
        u, v, w = map(int, input().split())
        edges.append((w, u, v))
    edges.sort()
    
    parent = [i for i in range(N + 1)]
    total_cost = 0
    max_edge = 0 # 마지막에 추가될 가장 비싼 간선 기록
    
    # 2. 크루스칼 알고리즘 수행
    for w, u, v in edges:
        # 두 집의 루트가 다르면 (사이클이 안 생기면) 연결!
        if find_parent(parent, u) != find_parent(parent, v):
            union_parent(parent, u, v)
            total_cost += w
            max_edge = w # 정렬되어 있으므로 나중에 들어오는 게 무조건 더 비쌈
            
    # 전체 연결 비용에서 가장 비싼 길 하나를 제거 (마을 분리)
    print(total_cost - max_edge)

if __name__ == "__main__":
    solve()
