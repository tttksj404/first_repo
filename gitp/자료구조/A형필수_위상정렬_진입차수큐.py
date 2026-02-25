'''
위상정렬(Topological Sort)
- 방향 그래프에서 "선행 -> 후행" 순서를 지키며 정점 나열
- DAG(사이클 없는 방향 그래프)에서만 전체 정렬 가능

핵심 개념
1) 진입차수(indegree): 자기로 들어오는 간선 수
2) 진입차수 0인 노드를 큐에 넣고 시작
3) 꺼낸 노드의 간선을 제거하며 다음 0차수 노드를 큐에 추가
4) 결과 길이가 N보다 작으면 사이클 존재
'''

from collections import deque

# 예시: 1,2가 3보다 먼저 / 3이 4보다 먼저 / 2가 5보다 먼저
N = 5
edges = [
    (1, 3),
    (2, 3),
    (3, 4),
    (2, 5),
]

adj = [[] for _ in range(N + 1)]
indegree = [0] * (N + 1)

for a, b in edges:
    adj[a].append(b)
    indegree[b] += 1

q = deque()
for i in range(1, N + 1):
    if indegree[i] == 0:
        q.append(i)

order = []
while q:
    cur = q.popleft()
    order.append(cur)

    for nxt in adj[cur]:
        indegree[nxt] -= 1
        if indegree[nxt] == 0:
            q.append(nxt)

if len(order) != N:
    print('사이클이 있어 위상정렬 불가')
else:
    print('[위상정렬 결과]')
    print(order)
