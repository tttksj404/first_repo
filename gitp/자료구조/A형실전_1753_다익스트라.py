# 자주 틀리는 포인트
# 1) heap에서 꺼낸 값이 dist와 다르면 stale 데이터이므로 continue
# 2) INF는 충분히 크게 설정하고 출력 시 INF 문자열 처리
# 3) 음수 가중치 그래프에는 다익스트라 사용 금지
import sys
import heapq

# BOJ 1753 최단경로

input = sys.stdin.readline
INF = 10 ** 18

V, E = map(int, input().split())
K = int(input())
adj = [[] for _ in range(V + 1)]

for _ in range(E):
    u, v, w = map(int, input().split())
    adj[u].append((v, w))


dist = [INF] * (V + 1)
dist[K] = 0
pq = [(0, K)]

while pq:
    cur, u = heapq.heappop(pq)
    if cur != dist[u]:
        continue

    for v, w in adj[u]:
        nd = cur + w
        if nd < dist[v]:
            dist[v] = nd
            heapq.heappush(pq, (nd, v))

for i in range(1, V + 1):
    if dist[i] == INF:
        print('INF')
    else:
        print(dist[i])

