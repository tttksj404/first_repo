'''
가중치 최단거리 기본형 (다익스트라)
- 음수 가중치 없는 그래프
- heapq로 현재 최소 거리부터 처리
'''

import heapq

INF = 10 ** 15
N = 6
start = 1

adj = [[] for _ in range(N + 1)]
# (다음 노드, 비용)
for a, b, w in [
    (1, 2, 2),
    (1, 3, 5),
    (2, 3, 1),
    (2, 4, 2),
    (3, 5, 3),
    (4, 5, 1),
    (4, 6, 4),
    (5, 6, 1),
]:
    adj[a].append((b, w))


dist = [INF] * (N + 1)
dist[start] = 0
pq = [(0, start)]  # (누적거리, 노드)

while pq:
    cur_dist, u = heapq.heappop(pq)

    if cur_dist != dist[u]:
        continue

    for v, w in adj[u]:
        nd = cur_dist + w
        if nd < dist[v]:
            dist[v] = nd
            heapq.heappush(pq, (nd, v))

print('[최단거리]')
for i in range(1, N + 1):
    print(i, dist[i])
