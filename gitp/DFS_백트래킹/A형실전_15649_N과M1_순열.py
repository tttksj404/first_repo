# 자주 틀리는 포인트
# 1) depth==M일 때 바로 return 안 하면 중복 출력 발생
# 2) visited 해제(path pop, visited False) 백트래킹 누락 주의
# 3) 출력 누적 후 한번에 print 해야 시간초과 방지
import sys

# BOJ 15649 N과 M (1)
# 1~N에서 중복 없이 M개 뽑아 순열 출력

input = sys.stdin.readline
N, M = map(int, input().split())

visited = [False] * (N + 1)
path = []
out = []


def dfs(depth):
    if depth == M:
        out.append(' '.join(map(str, path)))
        return

    for x in range(1, N + 1):
        if visited[x]:
            continue
        visited[x] = True
        path.append(x)

        dfs(depth + 1)

        path.pop()
        visited[x] = False


dfs(0)
print('\n'.join(out))

