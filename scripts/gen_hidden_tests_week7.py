#!/usr/bin/env python3
"""Week 7: 데이크스트라 4 + 분리집합 4 + 최단경로 4."""
from __future__ import annotations
import json, random, sys, heapq
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


# 13549 숨바꼭질 3
def solve_13549():
    n, k = map(int, input().split())
    INF = 10**9
    if n >= k:
        print(n - k); return
    LIMIT = 100001
    dist = [INF] * LIMIT
    dist[n] = 0
    pq = [(0, n)]
    while pq:
        d, x = heapq.heappop(pq)
        if d > dist[x]: continue
        if x == k:
            print(d); return
        if x * 2 < LIMIT and d < dist[x * 2]:
            dist[x * 2] = d; heapq.heappush(pq, (d, x * 2))
        if x + 1 < LIMIT and d + 1 < dist[x + 1]:
            dist[x + 1] = d + 1; heapq.heappush(pq, (d + 1, x + 1))
        if x - 1 >= 0 and d + 1 < dist[x - 1]:
            dist[x - 1] = d + 1; heapq.heappush(pq, (d + 1, x - 1))


def cases_13549():
    return ["5 17\n", "0 0\n", "5 4\n", "5 5\n", "1 100000\n", "100000 0\n"]


# 1238 파티
def solve_1238():
    import sys as _sys
    data = _sys.stdin.read().split()
    n = int(data[0]); m = int(data[1]); x = int(data[2])
    fwd = [[] for _ in range(n + 1)]
    rev = [[] for _ in range(n + 1)]
    idx = 3
    for _ in range(m):
        u = int(data[idx]); v = int(data[idx+1]); w = int(data[idx+2]); idx += 3
        fwd[u].append((v, w))
        rev[v].append((u, w))
    INF = 10**18
    def dijk(start, graph):
        dist = [INF] * (n + 1)
        dist[start] = 0
        pq = [(0, start)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]: continue
            for v, w in graph[u]:
                if d + w < dist[v]:
                    dist[v] = d + w
                    heapq.heappush(pq, (d + w, v))
        return dist
    out = dijk(x, fwd)
    inb = dijk(x, rev)
    print(max(out[i] + inb[i] for i in range(1, n + 1)))


def cases_1238():
    return [
        "4 8 2\n1 2 4\n1 3 2\n1 4 7\n2 1 1\n2 3 5\n3 1 2\n3 4 4\n4 2 3\n",
        "2 2 1\n1 2 5\n2 1 3\n",
        _gen_1238_random(100, 1000, 50),
    ]


def _gen_1238_random(n, m, x):
    rng = random.Random(1238)
    lines = [f"{n} {m} {x}"]
    for _ in range(m):
        u = rng.randint(1, n); v = rng.randint(1, n)
        while v == u: v = rng.randint(1, n)
        lines.append(f"{u} {v} {rng.randint(1, 100)}")
    return "\n".join(lines) + "\n"


# 1504 특정한 최단 경로
def solve_1504():
    import sys as _sys
    data = _sys.stdin.read().split()
    idx = 0
    N = int(data[idx]); idx += 1
    E = int(data[idx]); idx += 1
    adj = [[] for _ in range(N + 1)]
    for _ in range(E):
        a = int(data[idx]); b = int(data[idx+1]); c = int(data[idx+2]); idx += 3
        adj[a].append((b, c)); adj[b].append((a, c))
    v1 = int(data[idx]); v2 = int(data[idx+1])
    INF = 10**18
    def dijk(s):
        dist = [INF] * (N + 1)
        dist[s] = 0
        pq = [(0, s)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]: continue
            for v, w in adj[u]:
                if d + w < dist[v]:
                    dist[v] = d + w
                    heapq.heappush(pq, (d + w, v))
        return dist
    d1 = dijk(1); dv1 = dijk(v1); dv2 = dijk(v2)
    p1 = d1[v1] + dv1[v2] + dv2[N]
    p2 = d1[v2] + dv2[v1] + dv1[N]
    ans = min(p1, p2)
    print(-1 if ans >= INF else ans)


def cases_1504():
    return [
        "4 6\n1 2 3\n2 3 3\n3 4 1\n1 3 5\n2 4 5\n1 4 4\n2 3\n",
        "2 1\n1 2 1\n1 2\n",
        "5 4\n1 2 1\n2 3 1\n3 4 1\n4 5 1\n2 4\n",
        "3 0\n1 2\n",  # disconnected
    ]


# 1261 알고스팟
def solve_1261():
    from collections import deque
    m, n = map(int, input().split())
    g = [list(input().strip()) for _ in range(n)]
    INF = 10**18
    dist = [[INF] * m for _ in range(n)]
    dist[0][0] = 0
    dq = deque([(0, 0)])
    while dq:
        r, c = dq.popleft()
        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < n and 0 <= nc < m:
                cost = int(g[nr][nc])
                if dist[r][c] + cost < dist[nr][nc]:
                    dist[nr][nc] = dist[r][c] + cost
                    if cost == 0:
                        dq.appendleft((nr, nc))
                    else:
                        dq.append((nr, nc))
    print(dist[n-1][m-1])


def cases_1261():
    return [
        "1 1\n0\n",
        "3 3\n011\n111\n110\n",
        "4 4\n0000\n1111\n0000\n1111\n",
        "5 5\n00000\n00000\n00000\n00000\n00000\n",
    ]


# 1717 집합의 표현
def solve_1717():
    import sys as _sys
    sys.setrecursionlimit(2000000)
    data = _sys.stdin.read().split()
    n = int(data[0]); m = int(data[1])
    p = list(range(n + 1))
    def find(x):
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: p[ra] = rb
    out = []
    idx = 2
    for _ in range(m):
        op = int(data[idx]); a = int(data[idx+1]); b = int(data[idx+2]); idx += 3
        if op == 0: union(a, b)
        else: out.append("YES" if find(a) == find(b) else "NO")
    print("\n".join(out))


def cases_1717():
    return [
        "1 1\n1 0 0\n",
        "7 8\n0 1 3\n1 1 7\n0 7 6\n1 7 1\n0 3 7\n0 4 2\n0 1 1\n1 1 1\n",
        _gen_1717_random(1000, 5000),
    ]


def _gen_1717_random(n, m):
    rng = random.Random(1717)
    lines = [f"{n} {m}"]
    for _ in range(m):
        op = rng.randint(0, 1)
        a = rng.randint(0, n); b = rng.randint(0, n)
        lines.append(f"{op} {a} {b}")
    return "\n".join(lines) + "\n"


# 1976 여행 가자
def solve_1976():
    n = int(input()); m = int(input())
    p = list(range(n + 1))
    def find(x):
        while p[x] != x:
            p[x] = p[p[x]]; x = p[x]
        return x
    for i in range(1, n + 1):
        row = list(map(int, input().split()))
        for j in range(n):
            if row[j] == 1:
                a, b = find(i), find(j + 1)
                if a != b: p[a] = b
    plan = list(map(int, input().split()))
    root = find(plan[0])
    print("YES" if all(find(x) == root for x in plan) else "NO")


def cases_1976():
    return [
        "1\n1\n1\n1\n",
        "3\n3\n0 1 0\n1 0 1\n0 1 0\n1 2 3\n",
        "5\n4\n0 0 0 0 0\n0 0 0 0 0\n0 0 0 0 0\n0 0 0 0 0\n0 0 0 0 0\n1 2 3 4\n",
        "5\n4\n0 1 1 1 1\n1 0 1 1 1\n1 1 0 1 1\n1 1 1 0 1\n1 1 1 1 0\n5 4 3 2\n",
    ]


# 1043 거짓말
def solve_1043():
    n, m = map(int, input().split())
    truth = list(map(int, input().split()))
    truth_set = set(truth[1:])
    parties = []
    for _ in range(m):
        line = list(map(int, input().split()))
        parties.append(line[1:])
    p = list(range(n + 1))
    def find(x):
        while p[x] != x:
            p[x] = p[p[x]]; x = p[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: p[ra] = rb
    for party in parties:
        for i in range(1, len(party)):
            union(party[0], party[i])
    truth_roots = {find(t) for t in truth_set}
    cnt = 0
    for party in parties:
        if any(find(p) in truth_roots for p in party):
            continue
        cnt += 1
    print(cnt)


def cases_1043():
    return [
        "3 3\n1 1\n1 1\n2 2 3\n1 1\n",
        "10 9\n4 1 2 3 4\n2 1 5\n2 2 6\n1 7\n1 8\n2 7 8\n1 9\n1 10\n2 3 10\n1 4\n",
        "8 5\n3 1 2 7\n3 1 5 8\n4 1 2 3 4\n5 4 5 6 7 8\n2 6 7\n2 7 8\n",
        "10 0\n1 1\n",
    ]


# 4195 친구 네트워크
def solve_4195():
    import sys as _sys
    data = _sys.stdin.read().split()
    idx = 0
    t = int(data[idx]); idx += 1
    out = []
    for _ in range(t):
        f = int(data[idx]); idx += 1
        p = {}; size = {}
        def find(x):
            while p[x] != x:
                p[x] = p[p[x]]; x = p[x]
            return x
        for _ in range(f):
            a = data[idx]; b = data[idx+1]; idx += 2
            if a not in p: p[a] = a; size[a] = 1
            if b not in p: p[b] = b; size[b] = 1
            ra, rb = find(a), find(b)
            if ra != rb:
                p[ra] = rb
                size[rb] += size[ra]
            out.append(str(size[find(a)]))
    print("\n".join(out))


def cases_4195():
    return [
        "1\n1\nFred Barney\n",
        "2\n3\nFred Barney\nBarney Betty\nBetty Wilma\n3\nAlice Bob\nAlice Carol\nDave Eve\n",
        _gen_4195_random(1, 1000),
    ]


def _gen_4195_random(t, f):
    rng = random.Random(4195)
    lines = [str(t)]
    pool = [f"u{i}" for i in range(2 * f)]
    for _ in range(t):
        lines.append(str(f))
        for _ in range(f):
            a, b = rng.choice(pool), rng.choice(pool)
            while a == b: b = rng.choice(pool)
            lines.append(f"{a} {b}")
    return "\n".join(lines) + "\n"


# 1753 최단경로
def solve_1753():
    import sys as _sys
    data = _sys.stdin.read().split()
    idx = 0
    V = int(data[idx]); idx += 1
    E = int(data[idx]); idx += 1
    K = int(data[idx]); idx += 1
    adj = [[] for _ in range(V + 1)]
    for _ in range(E):
        u = int(data[idx]); v = int(data[idx+1]); w = int(data[idx+2]); idx += 3
        adj[u].append((v, w))
    INF = 10**18
    dist = [INF] * (V + 1)
    dist[K] = 0
    pq = [(0, K)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]: continue
        for v, w in adj[u]:
            if d + w < dist[v]:
                dist[v] = d + w
                heapq.heappush(pq, (d + w, v))
    out = []
    for i in range(1, V + 1):
        out.append("INF" if dist[i] == INF else str(dist[i]))
    print("\n".join(out))


def cases_1753():
    return [
        "5 6 1\n5 1 1\n1 2 2\n1 3 3\n2 3 4\n2 4 5\n3 4 6\n",
        "1 0 1\n",
        "3 0 2\n",
        "5 4 1\n1 2 1\n2 3 1\n3 4 1\n4 5 1\n",
    ]


# 7569 토마토 (3D)
def solve_7569():
    from collections import deque
    m, n, h = map(int, input().split())
    grid = []
    q = deque()
    unripe = 0
    for k in range(h):
        layer = []
        for i in range(n):
            row = list(map(int, input().split()))
            for j in range(m):
                if row[j] == 1: q.append((k, i, j, 0))
                elif row[j] == 0: unripe += 1
            layer.append(row)
        grid.append(layer)
    last = 0
    while q:
        z, r, c, d = q.popleft(); last = d
        for dz, dr, dc in [(-1,0,0),(1,0,0),(0,-1,0),(0,1,0),(0,0,-1),(0,0,1)]:
            nz, nr, nc = z + dz, r + dr, c + dc
            if 0 <= nz < h and 0 <= nr < n and 0 <= nc < m and grid[nz][nr][nc] == 0:
                grid[nz][nr][nc] = 1; unripe -= 1
                q.append((nz, nr, nc, d + 1))
    print(-1 if unripe > 0 else last)


def cases_7569():
    return [
        "1 1 1\n1\n",
        "1 1 1\n0\n",
        "1 1 1\n-1\n",
        "5 3 2\n0 0 0 0 0\n0 0 0 0 0\n0 0 0 0 0\n0 0 0 0 0\n0 0 0 0 0\n0 0 0 0 1\n",
        "5 3 2\n1 1 1 1 1\n1 1 1 1 1\n1 1 1 1 1\n1 1 1 1 1\n1 1 1 1 1\n1 1 1 1 1\n",
    ]


# 7562 나이트의 이동
def solve_7562():
    from collections import deque
    t = int(input())
    out = []
    moves = [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]
    for _ in range(t):
        n = int(input())
        sr, sc = map(int, input().split())
        tr, tc = map(int, input().split())
        if (sr, sc) == (tr, tc):
            out.append("0"); continue
        dist = [[-1]*n for _ in range(n)]
        dist[sr][sc] = 0
        q = deque([(sr, sc)])
        found = False
        while q and not found:
            r, c = q.popleft()
            for dr, dc in moves:
                nr, nc = r + dr, c + dc
                if 0 <= nr < n and 0 <= nc < n and dist[nr][nc] == -1:
                    dist[nr][nc] = dist[r][c] + 1
                    if (nr, nc) == (tr, tc):
                        out.append(str(dist[nr][nc])); found = True; break
                    q.append((nr, nc))
    print("\n".join(out))


def cases_7562():
    return [
        "1\n8\n0 0\n7 0\n",
        "3\n8\n0 0\n7 0\n100\n0 0\n30 50\n10\n1 1\n1 1\n",
        "1\n3\n0 0\n2 2\n",
    ]


# 1916 최소비용 구하기
def solve_1916():
    import sys as _sys
    data = _sys.stdin.read().split()
    idx = 0
    n = int(data[idx]); idx += 1
    m = int(data[idx]); idx += 1
    adj = [[] for _ in range(n + 1)]
    for _ in range(m):
        u = int(data[idx]); v = int(data[idx+1]); w = int(data[idx+2]); idx += 3
        adj[u].append((v, w))
    s = int(data[idx]); e = int(data[idx+1])
    INF = 10**18
    dist = [INF] * (n + 1)
    dist[s] = 0
    pq = [(0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]: continue
        if u == e: break
        for v, w in adj[u]:
            if d + w < dist[v]:
                dist[v] = d + w
                heapq.heappush(pq, (d + w, v))
    print(dist[e])


def cases_1916():
    return [
        "5\n8\n1 2 2\n1 3 3\n1 4 1\n1 5 10\n2 4 2\n3 4 1\n3 5 1\n4 5 3\n1 5\n",
        "2\n1\n1 2 5\n1 2\n",
        "3\n2\n1 2 5\n2 3 3\n1 3\n",
    ]


PROBLEMS = [
    (13549, solve_13549, cases_13549),
    (1238, solve_1238, cases_1238),
    (1504, solve_1504, cases_1504),
    (1261, solve_1261, cases_1261),
    (1717, solve_1717, cases_1717),
    (1976, solve_1976, cases_1976),
    (1043, solve_1043, cases_1043),
    (4195, solve_4195, cases_4195),
    (1753, solve_1753, cases_1753),
    (7569, solve_7569, cases_7569),
    (7562, solve_7562, cases_7562),
    (1916, solve_1916, cases_1916),
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
