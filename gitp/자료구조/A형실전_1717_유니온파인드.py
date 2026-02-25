# 자주 틀리는 포인트
# 1) find 경로압축 누락 시 시간초과 위험
# 2) union 전에 루트(find) 비교를 꼭 해야 함
# 3) 같은 집합 판별은 parent 직접 비교 말고 find(a)==find(b)
import sys

# BOJ 1717 집합의 표현
# 0 a b: 합치기
# 1 a b: 같은 집합이면 YES 아니면 NO

input = sys.stdin.readline
n, m = map(int, input().split())
parent = list(range(n + 1))


def find(x):
    if parent[x] != x:
        parent[x] = find(parent[x])
    return parent[x]


def union(a, b):
    ra = find(a)
    rb = find(b)
    if ra == rb:
        return
    if ra < rb:
        parent[rb] = ra
    else:
        parent[ra] = rb


out = []
for _ in range(m):
    op, a, b = map(int, input().split())
    if op == 0:
        union(a, b)
    else:
        out.append('YES' if find(a) == find(b) else 'NO')

print('\n'.join(out))

