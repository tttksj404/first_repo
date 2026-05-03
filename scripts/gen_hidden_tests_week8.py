#!/usr/bin/env python3
"""Week 8: MST 4 + 위상정렬 4 + 트리 4."""
from __future__ import annotations
import json, random, sys, math
from io import StringIO
from pathlib import Path

JUDGE = Path("/Users/tttksj/first_repo/offline_judge/data/finance/problems")
random.seed(20260427)


def run_solver(solver, stdin_text):
    old = sys.stdin, sys.stdout
    sys.stdin = StringIO(stdin_text)
    sys.stdout = buf = StringIO()
    sys.setrecursionlimit(200000)
    try:
        solver()
    finally:
        sys.stdin, sys.stdout = old
    return buf.getvalue()


# 1197 최소 스패닝 트리
def solve_1197():
    import sys as _sys
    data = _sys.stdin.read().split()
    v = int(data[0]); e = int(data[1])
    edges = []
    idx = 2
    for _ in range(e):
        a = int(data[idx]); b = int(data[idx+1]); c = int(data[idx+2]); idx += 3
        edges.append((c, a, b))
    edges.sort()
    p = list(range(v + 1))
    def find(x):
        while p[x] != x:
            p[x] = p[p[x]]; x = p[x]
        return x
    total = 0
    for c, a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            p[ra] = rb; total += c
    print(total)


def cases_1197():
    return [
        "3 3\n1 2 1\n2 3 2\n1 3 3\n",
        "1 0\n",
        "5 4\n1 2 1\n2 3 2\n3 4 3\n4 5 4\n",
        _gen_1197_random(100, 500),
    ]


def _gen_1197_random(v, e):
    rng = random.Random(1197)
    lines = [f"{v} {e}"]
    for _ in range(e):
        a = rng.randint(1, v); b = rng.randint(1, v)
        while a == b: b = rng.randint(1, v)
        lines.append(f"{a} {b} {rng.randint(-100, 100)}")
    return "\n".join(lines) + "\n"


# 1922 네트워크 연결
def solve_1922():
    import sys as _sys
    data = _sys.stdin.read().split()
    n = int(data[0]); m = int(data[1])
    edges = []
    idx = 2
    for _ in range(m):
        a = int(data[idx]); b = int(data[idx+1]); c = int(data[idx+2]); idx += 3
        edges.append((c, a, b))
    edges.sort()
    p = list(range(n + 1))
    def find(x):
        while p[x] != x:
            p[x] = p[p[x]]; x = p[x]
        return x
    total = 0
    for c, a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            p[ra] = rb; total += c
    print(total)


def cases_1922():
    return [
        "1 0\n",
        "3 3\n1 2 1\n2 3 2\n1 3 5\n",
        "4 5\n1 2 1\n2 3 2\n3 4 3\n1 4 4\n2 4 5\n",
        _gen_1197_random(50, 200),
    ]


# 1647 도시 분할 계획
def solve_1647():
    import sys as _sys
    data = _sys.stdin.read().split()
    n = int(data[0]); m = int(data[1])
    edges = []
    idx = 2
    for _ in range(m):
        a = int(data[idx]); b = int(data[idx+1]); c = int(data[idx+2]); idx += 3
        edges.append((c, a, b))
    edges.sort()
    p = list(range(n + 1))
    def find(x):
        while p[x] != x:
            p[x] = p[p[x]]; x = p[x]
        return x
    total = 0; max_edge = 0
    for c, a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            p[ra] = rb; total += c
            if c > max_edge: max_edge = c
    print(total - max_edge)


def cases_1647():
    return [
        "2 1\n1 2 5\n",
        "7 12\n1 2 3\n1 3 2\n3 2 1\n2 5 2\n3 4 4\n7 3 6\n5 1 5\n1 6 2\n6 4 1\n6 5 3\n4 5 3\n6 7 4\n",
        _gen_1647_random(100, 500),
    ]


def _gen_1647_random(n, m):
    rng = random.Random(1647)
    edges = set()
    while len(edges) < m:
        a = rng.randint(1, n); b = rng.randint(1, n)
        if a != b:
            edges.add((min(a, b), max(a, b), rng.randint(1, 100)))
    # ensure connected
    for i in range(2, n + 1):
        edges.add((1, i, rng.randint(1, 1000)))
    lines = [f"{n} {len(edges)}"]
    for a, b, c in edges:
        lines.append(f"{a} {b} {c}")
    return "\n".join(lines) + "\n"


# 4386 별자리 만들기
def solve_4386():
    n = int(input())
    pts = []
    for _ in range(n):
        x, y = map(float, input().split())
        pts.append((x, y))
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            d = math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
            edges.append((d, i, j))
    edges.sort()
    p = list(range(n))
    def find(x):
        while p[x] != x:
            p[x] = p[p[x]]; x = p[x]
        return x
    total = 0.0
    for d, a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            p[ra] = rb; total += d
    print(f"{total:.2f}")


def cases_4386():
    return [
        "3\n1.0 1.0\n2.0 2.0\n2.0 4.0\n",
        "1\n5.5 5.5\n",
        "2\n0 0\n3 4\n",
        "4\n0 0\n1 0\n0 1\n1 1\n",
    ]


# 2252 줄 세우기
def solve_2252():
    from collections import deque
    n, m = map(int, input().split())
    indeg = [0] * (n + 1)
    adj = [[] for _ in range(n + 1)]
    for _ in range(m):
        a, b = map(int, input().split())
        adj[a].append(b); indeg[b] += 1
    q = deque(i for i in range(1, n + 1) if indeg[i] == 0)
    order = []
    while q:
        x = q.popleft(); order.append(x)
        for y in adj[x]:
            indeg[y] -= 1
            if indeg[y] == 0: q.append(y)
    print(" ".join(map(str, order)))


def cases_2252():
    return [
        "2 1\n1 2\n",
        "3 0\n",
        "5 4\n1 2\n2 3\n3 4\n4 5\n",
        _gen_2252_random(100, 200),
    ]


def _gen_2252_random(n, m):
    rng = random.Random(2252)
    lines = [f"{n} {m}"]
    for _ in range(m):
        a = rng.randint(1, n - 1); b = rng.randint(a + 1, n)
        lines.append(f"{a} {b}")
    return "\n".join(lines) + "\n"


# 1005 ACM Craft
def solve_1005():
    from collections import deque
    t = int(input())
    out = []
    for _ in range(t):
        n, k = map(int, input().split())
        d = list(map(int, input().split()))
        adj = [[] for _ in range(n + 1)]
        indeg = [0] * (n + 1)
        for _ in range(k):
            a, b = map(int, input().split())
            adj[a].append(b); indeg[b] += 1
        w = int(input())
        cost = [0] * (n + 1)
        for i in range(1, n + 1):
            cost[i] = d[i - 1]
        q = deque()
        ind = indeg[:]
        for i in range(1, n + 1):
            if ind[i] == 0: q.append(i)
        while q:
            x = q.popleft()
            for y in adj[x]:
                if cost[x] + d[y - 1] > cost[y]:
                    cost[y] = cost[x] + d[y - 1]
                ind[y] -= 1
                if ind[y] == 0: q.append(y)
        out.append(str(cost[w]))
    print("\n".join(out))


def cases_1005():
    return [
        "2\n4 4\n10 1 100 10\n1 2\n1 3\n2 4\n3 4\n4\n8 8\n10 20 1 5 8 7 1 43\n1 2\n1 3\n2 4\n2 5\n3 6\n5 7\n6 7\n7 8\n7\n",
        "1\n3 0\n5 6 7\n2\n",
        "1\n5 4\n1 2 3 4 5\n1 2\n2 3\n3 4\n4 5\n5\n",
    ]


# 1766 문제집
def solve_1766():
    import heapq
    n, m = map(int, input().split())
    indeg = [0] * (n + 1)
    adj = [[] for _ in range(n + 1)]
    for _ in range(m):
        a, b = map(int, input().split())
        adj[a].append(b); indeg[b] += 1
    pq = [i for i in range(1, n + 1) if indeg[i] == 0]
    heapq.heapify(pq)
    order = []
    while pq:
        x = heapq.heappop(pq)
        order.append(x)
        for y in adj[x]:
            indeg[y] -= 1
            if indeg[y] == 0: heapq.heappush(pq, y)
    print(" ".join(map(str, order)))


def cases_1766():
    return [
        "1 0\n",
        "4 2\n4 2\n3 1\n",
        "5 4\n1 4\n4 2\n5 4\n3 1\n",
        _gen_2252_random(50, 100),
    ]


# 2623 음악프로그램
def solve_2623():
    from collections import deque
    n, m = map(int, input().split())
    indeg = [0] * (n + 1)
    adj = [[] for _ in range(n + 1)]
    for _ in range(m):
        line = list(map(int, input().split()))
        seq = line[1:]
        for i in range(len(seq) - 1):
            adj[seq[i]].append(seq[i + 1])
            indeg[seq[i + 1]] += 1
    q = deque(i for i in range(1, n + 1) if indeg[i] == 0)
    order = []
    while q:
        x = q.popleft(); order.append(x)
        for y in adj[x]:
            indeg[y] -= 1
            if indeg[y] == 0: q.append(y)
    if len(order) != n:
        print(0)
    else:
        print("\n".join(map(str, order)))


def cases_2623():
    return [
        "1 0\n",
        "6 3\n3 1 4 3\n4 6 2 5 4\n2 2 3\n",
        "3 1\n3 1 2 3\n",
        "3 2\n2 1 2\n2 2 1\n",  # cycle -> 0
    ]


# 1991 트리 순회
def solve_1991():
    n = int(input())
    children = {}
    for _ in range(n):
        a, b, c = input().split()
        children[a] = (b, c)
    pre = []; ino = []; po = []
    def dfs(x):
        if x == ".": return
        b, c = children[x]
        pre.append(x); dfs(b)
        ino.append(x); dfs(c)
        po.append(x)
    dfs("A")
    print("".join(pre))
    print("".join(ino))
    print("".join(po))


def cases_1991():
    return [
        "1\nA . .\n",
        "7\nA B C\nB D .\nC E F\nE . .\nF . G\nD . .\nG . .\n",
        "3\nA B .\nB C .\nC . .\n",
    ]


# 1967 트리의 지름
def solve_1967():
    from collections import deque
    n = int(input())
    if n == 1:
        print(0); return
    adj = [[] for _ in range(n + 1)]
    for _ in range(n - 1):
        a, b, c = map(int, input().split())
        adj[a].append((b, c)); adj[b].append((a, c))
    def bfs(s):
        dist = [-1] * (n + 1)
        dist[s] = 0
        q = deque([s])
        far = (s, 0)
        while q:
            x = q.popleft()
            for y, w in adj[x]:
                if dist[y] == -1:
                    dist[y] = dist[x] + w
                    if dist[y] > far[1]:
                        far = (y, dist[y])
                    q.append(y)
        return far
    u, _ = bfs(1)
    _, d = bfs(u)
    print(d)


def cases_1967():
    return [
        "1\n",
        "12\n1 2 3\n1 3 2\n2 4 5\n3 5 11\n3 6 9\n4 7 1\n4 8 7\n5 9 15\n5 10 4\n6 11 6\n6 12 10\n",
        "2\n1 2 100\n",
        _gen_tree_weighted(100, 1967),
    ]


def _gen_tree_weighted(n, seed):
    rng = random.Random(seed)
    lines = [str(n)]
    for i in range(2, n + 1):
        p = rng.randint(1, i - 1)
        lines.append(f"{p} {i} {rng.randint(1, 1000)}")
    return "\n".join(lines) + "\n"


# 1167 트리의 지름 (다른 입력 포맷)
def solve_1167():
    import sys as _sys
    from collections import deque
    data = _sys.stdin.read().split()
    n = int(data[0])
    adj = [[] for _ in range(n + 1)]
    idx = 1
    for _ in range(n):
        v = int(data[idx]); idx += 1
        while True:
            x = int(data[idx]); idx += 1
            if x == -1: break
            w = int(data[idx]); idx += 1
            adj[v].append((x, w))
    if n == 1:
        print(0); return
    def bfs(s):
        dist = [-1] * (n + 1); dist[s] = 0
        q = deque([s]); far = (s, 0)
        while q:
            x = q.popleft()
            for y, w in adj[x]:
                if dist[y] == -1:
                    dist[y] = dist[x] + w
                    if dist[y] > far[1]:
                        far = (y, dist[y])
                    q.append(y)
        return far
    u, _ = bfs(1)
    _, d = bfs(u)
    print(d)


def cases_1167():
    return [
        "1\n1 -1\n",
        "5\n1 3 2 -1\n2 4 4 -1\n3 1 2 4 3 -1\n4 2 4 3 3 5 6 -1\n5 4 6 -1\n",
        "2\n1 2 100 -1\n2 1 100 -1\n",
    ]


# 1068 트리
def solve_1068():
    n = int(input())
    parents = list(map(int, input().split()))
    delete = int(input())
    children = [[] for _ in range(n)]
    root = -1
    for i, p in enumerate(parents):
        if p == -1: root = i
        else: children[p].append(i)
    if root == delete:
        print(0); return
    # mark deleted subtree
    deleted = set()
    stack = [delete]
    while stack:
        x = stack.pop()
        deleted.add(x)
        stack.extend(children[x])
    # count leaves in remaining
    cnt = 0
    for i in range(n):
        if i in deleted: continue
        if not any(c not in deleted for c in children[i]):
            cnt += 1
    print(cnt)


def cases_1068():
    return [
        "1\n-1\n0\n",
        "5\n-1 0 0 1 1\n2\n",
        "5\n-1 0 0 1 1\n1\n",
        "9\n-1 0 0 2 2 4 4 6 6\n4\n",
    ]


PROBLEMS = [
    (1197, solve_1197, cases_1197),
    (1922, solve_1922, cases_1922),
    (1647, solve_1647, cases_1647),
    (4386, solve_4386, cases_4386),
    (2252, solve_2252, cases_2252),
    (1005, solve_1005, cases_1005),
    (1766, solve_1766, cases_1766),
    (2623, solve_2623, cases_2623),
    (1991, solve_1991, cases_1991),
    (1967, solve_1967, cases_1967),
    (1167, solve_1167, cases_1167),
    (1068, solve_1068, cases_1068),
]


def write_hidden_tests(pid, solver, cases):
    pdir = JUDGE / str(pid)
    if not pdir.exists(): return 0
    for f in pdir.glob("hidden*.in"): f.unlink()
    for f in pdir.glob("hidden*.out"): f.unlink()
    n_written = 0
    for i, inp in enumerate(cases, 1):
        out = run_solver(solver, inp)
        (pdir / f"hidden{i}.in").write_text(inp, encoding="utf-8")
        (pdir / f"hidden{i}.out").write_text(out, encoding="utf-8")
        n_written += 1
    meta_path = pdir / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["hidden_count"] = n_written
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return n_written


if __name__ == "__main__":
    total = 0
    for pid, solver, gen in PROBLEMS:
        n = write_hidden_tests(pid, solver, gen())
        total += n
        print(f"  [{pid}] +{n}")
    print(f"DONE: {total} / {len(PROBLEMS)}")
