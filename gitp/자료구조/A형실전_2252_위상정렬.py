# 자주 틀리는 포인트
# 1) 간선 방향(a->b) 반대로 넣으면 정답이 완전히 바뀜
# 2) 시작은 indegree==0 노드 전부를 큐에 넣어야 함
# 3) 결과 개수가 N보다 작으면 사이클(문제 조건 위배) 가능성 확인

import sys
from collections import deque

# BOJ 2252 줄 세우기
# 입력: N M, 이후 M개의 a b (a가 b보다 앞)

input = sys.stdin.readline
N, M = map(int, input().split())

adj = [[] for _ in range(N + 1)]
indegree = [0] * (N + 1)

for _ in range(M):
    a, b = map(int, input().split())
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

print(*order)
