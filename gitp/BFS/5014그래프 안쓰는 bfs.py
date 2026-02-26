'''
기존 메모(복원):
- 시작 층 S에서 목표 층 G까지 가는 최소 버튼 횟수를 구하는 문제라서 BFS를 사용한다.
- 각 노드는 "현재 층"이고, 이동은 두 가지(위로 U층, 아래로 D층)만 존재한다.
- 건물 범위(1층 ~ F층)를 벗어나는 이동은 버린다.
- BFS에서 목표 층에 처음 도달했을 때의 횟수가 최소 버튼 횟수다.
'''

from collections import deque
import sys

# F: 총 층수, S: 현재 층, G: 목표 층, U: 위로 이동, D: 아래로 이동
F, S, G, U, D = map(int, sys.stdin.readline().split())


def bfs(start, goal):
    # 시작 층과 목표 층이 같으면 버튼을 누를 필요가 없다.
    if start == goal:
        return 0

    # dist[x] = start에서 x층까지 가는 최소 버튼 횟수, -1은 아직 미방문
    dist = [-1] * (F + 1)
    dist[start] = 0
    queue = deque([start])

    while queue:
        current = queue.popleft()

        # 현재 층에서 갈 수 있는 다음 층 2가지
        for nxt in (current + U, current - D):
            # 건물 범위 안에 있고 아직 방문하지 않은 층만 탐색
            if 1 <= nxt <= F and dist[nxt] == -1:
                dist[nxt] = dist[current] + 1

                # BFS 특성상 처음 도착한 거리가 최소 거리
                if nxt == goal:
                    return dist[nxt]

                queue.append(nxt)

    # 목표 층에 도달할 수 없는 경우
    return -1


answer = bfs(S, G)
if answer == -1:
    print("use the stairs")
else:
    print(answer)
