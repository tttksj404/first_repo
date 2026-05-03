#!/usr/bin/env python3
"""Week 5: BFS 4 + DFS 4 + 그래프 탐색 4."""
from __future__ import annotations
import json, random, sys
from io import StringIO
from pathlib import Path

JUDGE = Path("/Users/tttksj/first_repo/offline_judge/data/finance/problems")
random.seed(20260427)


def run_solver(solver, stdin_text):
    old = sys.stdin, sys.stdout
    sys.stdin = StringIO(stdin_text)
    sys.stdout = buf = StringIO()
    sys.setrecursionlimit(100000)
    try:
        solver()
    finally:
        sys.stdin, sys.stdout = old
    return buf.getvalue()


# 1012 유기농 배추
def solve_1012():
    from collections import deque
    t = int(input())
    out = []
    for _ in range(t):
        m, n, k = map(int, input().split())
        g = [[0]*m for _ in range(n)]
        for _ in range(k):
            x, y = map(int, input().split())
            g[y][x] = 1
        cnt = 0
        for i in range(n):
            for j in range(m):
                if g[i][j] == 1:
                    cnt += 1
                    q = deque([(i, j)])
                    g[i][j] = 0
                    while q:
                        r, c = q.popleft()
                        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < n and 0 <= nc < m and g[nr][nc] == 1:
                                g[nr][nc] = 0
                                q.append((nr, nc))
        out.append(str(cnt))
    print("\n".join(out))


def cases_1012():
    return [
        "1\n1 1 1\n0 0\n",
        "2\n5 3 6\n0 2\n1 2\n2 2\n3 2\n4 2\n4 0\n10 10 1\n5 5\n",
        _gen_1012_random(50, 50, 200, 1012),
    ]


def _gen_1012_random(m, n, k, seed):
    rng = random.Random(seed)
    coords = rng.sample(range(m*n), k)
    lines = [f"1\n{m} {n} {k}"]
    for c in coords:
        lines.append(f"{c % m} {c // m}")
    return "\n".join(lines) + "\n"


# 7576 토마토
def solve_7576():
    from collections import deque
    m, n = map(int, input().split())
    g = [list(map(int, input().split())) for _ in range(n)]
    q = deque()
    unripe = 0
    for i in range(n):
        for j in range(m):
            if g[i][j] == 1: q.append((i, j, 0))
            elif g[i][j] == 0: unripe += 1
    last = 0
    while q:
        r, c, d = q.popleft()
        last = d
        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < n and 0 <= nc < m and g[nr][nc] == 0:
                g[nr][nc] = 1
                unripe -= 1
                q.append((nr, nc, d + 1))
    print(-1 if unripe > 0 else last)


def cases_7576():
    return [
        "1 1\n1\n",
        "1 1\n0\n",
        "1 1\n-1\n",
        "6 4\n0 0 0 0 0 0\n0 0 0 0 0 0\n0 0 0 0 0 0\n0 0 0 0 0 1\n",
        "5 5\n-1 1 0 0 0\n0 -1 -1 -1 0\n0 -1 0 0 0\n0 -1 -1 -1 0\n0 0 0 0 0\n",
    ]


# 1697 숨바꼭질
def solve_1697():
    from collections import deque
    n, k = map(int, input().split())
    if n >= k:
        print(n - k); return
    seen = [False] * 200001
    q = deque([(n, 0)])
    seen[n] = True
    while q:
        x, d = q.popleft()
        if x == k:
            print(d); return
        for nx in (x - 1, x + 1, x * 2):
            if 0 <= nx < 200001 and not seen[nx]:
                seen[nx] = True
                q.append((nx, d + 1))


def cases_1697():
    return [
        "5 17\n",
        "0 0\n",
        "100000 0\n",
        "0 100000\n",
        "5 6\n",
        "5 4\n",
    ]


# 11724 연결 요소의 개수
def solve_11724():
    import sys as _sys
    data = _sys.stdin.read().split()
    n = int(data[0]); m = int(data[1])
    adj = [[] for _ in range(n + 1)]
    idx = 2
    for _ in range(m):
        u = int(data[idx]); v = int(data[idx+1]); idx += 2
        adj[u].append(v); adj[v].append(u)
    seen = [False] * (n + 1)
    cnt = 0
    for s in range(1, n + 1):
        if seen[s]: continue
        cnt += 1
        stack = [s]; seen[s] = True
        while stack:
            x = stack.pop()
            for y in adj[x]:
                if not seen[y]:
                    seen[y] = True; stack.append(y)
    print(cnt)


def cases_11724():
    return [
        "1 0\n",
        "5 0\n",  # 5 components
        "6 5\n1 2\n2 5\n5 1\n3 4\n4 6\n",
        "10 9\n1 2\n2 3\n3 4\n4 5\n5 6\n6 7\n7 8\n8 9\n9 10\n",  # 1 chain
        _gen_11724_random(1000, 1500),
    ]


def _gen_11724_random(n, m):
    rng = random.Random(11724)
    edges = set()
    while len(edges) < m:
        u = rng.randint(1, n); v = rng.randint(1, n)
        if u != v:
            edges.add((min(u,v), max(u,v)))
    lines = [f"{n} {m}"]
    for u, v in edges:
        lines.append(f"{u} {v}")
    return "\n".join(lines) + "\n"


# 10026 적록색약
def solve_10026():
    n = int(input())
    g = [input().strip() for _ in range(n)]
    def count(rg):
        seen = [[False]*n for _ in range(n)]
        c = 0
        for i in range(n):
            for j in range(n):
                if not seen[i][j]:
                    c += 1
                    color = rg[i][j]
                    stack = [(i, j)]; seen[i][j] = True
                    while stack:
                        r, q = stack.pop()
                        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
                            nr, nc = r + dr, q + dc
                            if 0 <= nr < n and 0 <= nc < n and not seen[nr][nc] and rg[nr][nc] == color:
                                seen[nr][nc] = True
                                stack.append((nr, nc))
        return c
    n1 = count(g)
    g2 = [row.replace("G", "R") for row in g]
    n2 = count(g2)
    print(n1, n2)


def cases_10026():
    return [
        "1\nR\n",
        "5\nRRRBB\nGGBBB\nBBBRR\nBBRRR\nRRRRR\n",
        "3\nRGB\nRGB\nRGB\n",
        "4\nRRRR\nRRRR\nRRRR\nRRRR\n",
        _gen_10026_random(50, 10026),
    ]


def _gen_10026_random(n, seed):
    rng = random.Random(seed)
    rows = ["".join(rng.choice("RGB") for _ in range(n)) for _ in range(n)]
    return f"{n}\n" + "\n".join(rows) + "\n"


# 11725 트리의 부모 찾기
def solve_11725():
    import sys as _sys
    from collections import deque
    data = _sys.stdin.read().split()
    n = int(data[0])
    adj = [[] for _ in range(n + 1)]
    idx = 1
    for _ in range(n - 1):
        a = int(data[idx]); b = int(data[idx+1]); idx += 2
        adj[a].append(b); adj[b].append(a)
    parent = [0] * (n + 1)
    seen = [False] * (n + 1)
    seen[1] = True
    q = deque([1])
    while q:
        x = q.popleft()
        for y in adj[x]:
            if not seen[y]:
                seen[y] = True; parent[y] = x; q.append(y)
    print("\n".join(str(parent[i]) for i in range(2, n + 1)))


def cases_11725():
    return [
        "2\n1 2\n",
        "7\n1 6\n6 3\n3 5\n4 1\n2 4\n4 7\n",
        _gen_tree(100, 11725),
        _gen_tree(1000, 11726),
    ]


def _gen_tree(n, seed):
    rng = random.Random(seed)
    lines = [str(n)]
    for i in range(2, n + 1):
        p = rng.randint(1, i - 1)
        lines.append(f"{p} {i}")
    return "\n".join(lines) + "\n"


# 2468 안전 영역
def solve_2468():
    n = int(input())
    g = [list(map(int, input().split())) for _ in range(n)]
    mx = max(max(r) for r in g)
    best = 1
    for h in range(0, mx):
        seen = [[False]*n for _ in range(n)]
        c = 0
        for i in range(n):
            for j in range(n):
                if g[i][j] > h and not seen[i][j]:
                    c += 1
                    stack = [(i, j)]; seen[i][j] = True
                    while stack:
                        r, q = stack.pop()
                        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
                            nr, nc = r + dr, q + dc
                            if 0 <= nr < n and 0 <= nc < n and not seen[nr][nc] and g[nr][nc] > h:
                                seen[nr][nc] = True; stack.append((nr, nc))
        if c > best:
            best = c
    print(best)


def cases_2468():
    return [
        "1\n5\n",
        "5\n6 8 2 6 2\n3 2 3 4 6\n6 7 3 3 2\n7 2 5 3 6\n8 9 5 2 7\n",
        "3\n1 1 1\n1 1 1\n1 1 1\n",  # all same
        _gen_2468_random(50, 2468),
    ]


def _gen_2468_random(n, seed):
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        rows.append(" ".join(str(rng.randint(1, 100)) for _ in range(n)))
    return f"{n}\n" + "\n".join(rows) + "\n"


# 4963 섬의 개수
def solve_4963():
    out = []
    while True:
        line = input().split()
        w, h = int(line[0]), int(line[1])
        if w == 0 and h == 0: break
        g = [list(map(int, input().split())) for _ in range(h)]
        seen = [[False]*w for _ in range(h)]
        c = 0
        for i in range(h):
            for j in range(w):
                if g[i][j] == 1 and not seen[i][j]:
                    c += 1
                    stack = [(i, j)]; seen[i][j] = True
                    while stack:
                        r, q = stack.pop()
                        for dr in (-1,0,1):
                            for dc in (-1,0,1):
                                if dr==0 and dc==0: continue
                                nr, nc = r + dr, q + dc
                                if 0 <= nr < h and 0 <= nc < w and not seen[nr][nc] and g[nr][nc] == 1:
                                    seen[nr][nc] = True; stack.append((nr, nc))
        out.append(str(c))
    print("\n".join(out))


def cases_4963():
    return [
        "1 1\n0\n0 0\n",
        "1 1\n1\n0 0\n",
        "5 4\n1 1 0 0 0\n1 1 0 1 1\n0 0 0 0 0\n0 0 0 1 0\n0 0\n",
        "5 5\n1 0 1 0 1\n0 1 0 1 0\n1 0 1 0 1\n0 1 0 1 0\n1 0 1 0 1\n0 0\n",  # diagonals
    ]


# 1260 DFS와 BFS
def solve_1260():
    from collections import deque
    n, m, v = map(int, input().split())
    adj = [set() for _ in range(n + 1)]
    for _ in range(m):
        a, b = map(int, input().split())
        adj[a].add(b); adj[b].add(a)
    adj_sorted = [sorted(s) for s in adj]
    # DFS
    dfs_order = []
    visited = [False] * (n + 1)
    def dfs(x):
        visited[x] = True
        dfs_order.append(x)
        for y in adj_sorted[x]:
            if not visited[y]:
                dfs(y)
    dfs(v)
    # BFS
    bfs_order = []
    seen = [False] * (n + 1)
    seen[v] = True
    q = deque([v])
    while q:
        x = q.popleft()
        bfs_order.append(x)
        for y in adj_sorted[x]:
            if not seen[y]:
                seen[y] = True; q.append(y)
    print(" ".join(map(str, dfs_order)))
    print(" ".join(map(str, bfs_order)))


def cases_1260():
    return [
        "1 0 1\n",
        "4 5 1\n1 2\n1 3\n1 4\n2 4\n3 4\n",
        "5 5 3\n5 4\n5 2\n1 2\n3 4\n3 1\n",
        "1000 1 1\n1 2\n",
    ]


# 2178 미로 탐색
def solve_2178():
    from collections import deque
    n, m = map(int, input().split())
    g = [input().strip() for _ in range(n)]
    dist = [[-1]*m for _ in range(n)]
    dist[0][0] = 1
    q = deque([(0, 0)])
    while q:
        r, c = q.popleft()
        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < n and 0 <= nc < m and g[nr][nc] == "1" and dist[nr][nc] == -1:
                dist[nr][nc] = dist[r][c] + 1
                q.append((nr, nc))
    print(dist[n-1][m-1])


def cases_2178():
    return [
        "1 1\n1\n",
        "4 6\n101111\n101010\n101011\n111011\n",
        "2 25\n1011101110111011101110111\n1110111011101110111011101\n",
        "5 5\n11111\n00001\n11111\n10000\n11111\n",
    ]


# 2606 바이러스
def solve_2606():
    n = int(input()); m = int(input())
    adj = [[] for _ in range(n + 1)]
    for _ in range(m):
        a, b = map(int, input().split())
        adj[a].append(b); adj[b].append(a)
    seen = [False] * (n + 1)
    seen[1] = True
    stack = [1]; cnt = 0
    while stack:
        x = stack.pop()
        for y in adj[x]:
            if not seen[y]:
                seen[y] = True; cnt += 1; stack.append(y)
    print(cnt)


def cases_2606():
    return [
        "1\n0\n",
        "7\n6\n1 2\n2 3\n1 5\n5 2\n5 6\n4 7\n",
        "5\n0\n",
        "100\n3\n1 2\n2 3\n3 1\n",
    ]


# 2667 단지번호붙이기
def solve_2667():
    n = int(input())
    g = [list(input().strip()) for _ in range(n)]
    sizes = []
    for i in range(n):
        for j in range(n):
            if g[i][j] == "1":
                sz = 0
                stack = [(i, j)]; g[i][j] = "0"
                while stack:
                    r, c = stack.pop(); sz += 1
                    for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
                        nr, nc = r + dr, c + dc
                        if 0 <= nr < n and 0 <= nc < n and g[nr][nc] == "1":
                            g[nr][nc] = "0"; stack.append((nr, nc))
                sizes.append(sz)
    sizes.sort()
    print(len(sizes))
    print("\n".join(map(str, sizes)))


def cases_2667():
    return [
        "1\n1\n",
        "1\n0\n",
        "7\n0110100\n0110101\n1110101\n0000111\n0100000\n0111110\n0111000\n",
        _gen_2667_random(25, 2667),
    ]


def _gen_2667_random(n, seed):
    rng = random.Random(seed)
    rows = ["".join(rng.choice("01") for _ in range(n)) for _ in range(n)]
    return f"{n}\n" + "\n".join(rows) + "\n"


PROBLEMS = [
    (1012, solve_1012, cases_1012),
    (7576, solve_7576, cases_7576),
    (1697, solve_1697, cases_1697),
    (11724, solve_11724, cases_11724),
    (10026, solve_10026, cases_10026),
    (11725, solve_11725, cases_11725),
    (2468, solve_2468, cases_2468),
    (4963, solve_4963, cases_4963),
    (1260, solve_1260, cases_1260),
    (2178, solve_2178, cases_2178),
    (2606, solve_2606, cases_2606),
    (2667, solve_2667, cases_2667),
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
    print(f"DONE: {total} / {len(PROBLEMS)} problems")
