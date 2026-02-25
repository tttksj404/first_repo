'''
유니온 파인드(Disjoint Set)
- 같은 팀/같은 집합 묶기
- 사이클 판별
- MST(크루스칼) 기본 도구
'''

N = 7
edges = [
    (1, 2),
    (2, 3),
    (4, 5),
    (5, 6),
    (6, 7),
    (3, 7),
    (2, 7),  # 여기서 사이클 발생 가능
]

parent = [i for i in range(N + 1)]


def find(x):
    if parent[x] != x:
        parent[x] = find(parent[x])
    return parent[x]


def union(a, b):
    ra = find(a)
    rb = find(b)
    if ra == rb:
        return False

    if ra < rb:
        parent[rb] = ra
    else:
        parent[ra] = rb
    return True


for a, b in edges:
    if not union(a, b):
        print(f'사이클 발생 간선: {a}-{b}')

print('[최종 parent]')
print(parent)
