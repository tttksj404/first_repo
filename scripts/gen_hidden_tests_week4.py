#!/usr/bin/env python3
"""Week 4: 매개변수 탐색 3 + 시뮬레이션 6 + 투포인터 3."""
from __future__ import annotations
import json, random, sys
from io import StringIO
from pathlib import Path
from typing import Callable, List

JUDGE = Path("/Users/tttksj/first_repo/offline_judge/data/finance/problems")
random.seed(20260427)


def run_solver(solver: Callable[[], None], stdin_text: str) -> str:
    old = sys.stdin, sys.stdout
    sys.stdin = StringIO(stdin_text)
    sys.stdout = buf = StringIO()
    try:
        solver()
    finally:
        sys.stdin, sys.stdout = old
    return buf.getvalue()


# 2343 기타 레슨 (매개변수 탐색)
def solve_2343():
    n, m = map(int, input().split())
    L = list(map(int, input().split()))
    lo, hi = max(L), sum(L)
    while lo <= hi:
        mid = (lo + hi) // 2
        cnt = 1; cur = 0
        for x in L:
            if cur + x > mid:
                cnt += 1; cur = x
            else:
                cur += x
        if cnt <= m: hi = mid - 1
        else: lo = mid + 1
    print(lo)


def cases_2343():
    return [
        "1 1\n1\n",
        "5 5\n1 2 3 4 5\n",
        "5 1\n1 2 3 4 5\n",
        "9 3\n1 2 3 4 5 6 7 8 9\n",
        _gen_2343_random(1000, 50),
    ]


def _gen_2343_random(n, m):
    rng = random.Random(2343)
    L = [rng.randint(1, 1000) for _ in range(n)]
    return f"{n} {m}\n{' '.join(map(str, L))}\n"


# 6236 용돈 관리
def solve_6236():
    n, m = map(int, input().split())
    a = [int(input()) for _ in range(n)]
    lo, hi = max(a), sum(a)
    ans = hi
    while lo <= hi:
        mid = (lo + hi) // 2
        cnt = 1; cur = mid
        ok = True
        for x in a:
            if x > mid:
                ok = False; break
            if cur < x:
                cnt += 1; cur = mid
            cur -= x
        if ok and cnt <= m:
            ans = mid; hi = mid - 1
        else:
            lo = mid + 1
    print(ans)


def cases_6236():
    return [
        "1 1\n100\n",
        "7 2\n" + "\n".join(["100"] * 7) + "\n",
        "4 3\n10\n20\n30\n40\n",
        _gen_6236_random(100000, 100),
    ]


def _gen_6236_random(n, m):
    rng = random.Random(6236)
    a = [rng.randint(1, 10000) for _ in range(n)]
    return f"{n} {m}\n" + "\n".join(map(str, a)) + "\n"


# 16401 과자 나눠주기
def solve_16401():
    m, n = map(int, input().split())
    L = list(map(int, input().split()))
    lo, hi = 1, max(L)
    ans = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        cnt = sum(x // mid for x in L)
        if cnt >= m:
            ans = mid; lo = mid + 1
        else:
            hi = mid - 1
    print(ans)


def cases_16401():
    return [
        "5 3\n2 5 8\n",
        "1 1\n1000000000\n",
        "10 1\n5\n",
        "100 5\n10 20 30 40 50\n",
        _gen_16401_random(1000000, 100000),
    ]


def _gen_16401_random(m, n):
    rng = random.Random(16401)
    L = [rng.randint(1, 1000000000) for _ in range(n)]
    return f"{m} {n}\n{' '.join(map(str, L))}\n"


# 14503 로봇 청소기
def solve_14503():
    n, m = map(int, input().split())
    r, c, d = map(int, input().split())
    grid = [list(map(int, input().split())) for _ in range(n)]
    cleaned = 0
    dr = [-1, 0, 1, 0]
    dc = [0, 1, 0, -1]
    while True:
        if grid[r][c] == 0:
            grid[r][c] = 2
            cleaned += 1
        found = False
        for _ in range(4):
            d = (d + 3) % 4
            nr = r + dr[d]; nc = c + dc[d]
            if 0 <= nr < n and 0 <= nc < m and grid[nr][nc] == 0:
                r, c = nr, nc
                found = True
                break
        if not found:
            back_d = (d + 2) % 4
            nr = r + dr[back_d]; nc = c + dc[back_d]
            if 0 <= nr < n and 0 <= nc < m and grid[nr][nc] != 1:
                r, c = nr, nc
            else:
                print(cleaned); return


def cases_14503():
    return [
        "3 3\n1 1 0\n1 1 1\n1 0 1\n1 1 1\n",
        "11 10\n7 4 0\n" + "\n".join([
            "1 1 1 1 1 1 1 1 1 1",
            "1 0 0 0 0 0 0 0 0 1",
            "1 0 0 0 1 1 1 1 0 1",
            "1 0 0 1 1 0 0 0 0 1",
            "1 0 1 1 0 0 0 1 0 1",
            "1 0 0 0 0 0 0 1 0 1",
            "1 0 0 0 0 1 0 1 0 1",
            "1 0 0 0 0 1 1 1 0 1",
            "1 0 0 0 0 0 0 0 0 1",
            "1 0 0 0 0 0 0 0 0 1",
            "1 1 1 1 1 1 1 1 1 1",
        ]) + "\n",
        "5 5\n2 2 0\n1 1 1 1 1\n1 0 0 0 1\n1 0 0 0 1\n1 0 0 0 1\n1 1 1 1 1\n",
    ]


# 3190 뱀
def solve_3190():
    n = int(input())
    k = int(input())
    apples = set()
    for _ in range(k):
        a, b = map(int, input().split())
        apples.add((a - 1, b - 1))
    L = int(input())
    turns = []
    for _ in range(L):
        x, c = input().split()
        turns.append((int(x), c))
    from collections import deque
    body = deque([(0, 0)])
    occ = {(0, 0)}
    dr = [0, 1, 0, -1]
    dc = [1, 0, -1, 0]
    d = 0
    t = 0
    ti = 0
    while True:
        t += 1
        nr = body[0][0] + dr[d]
        nc = body[0][1] + dc[d]
        if not (0 <= nr < n and 0 <= nc < n):
            print(t); return
        if (nr, nc) in occ:
            print(t); return
        body.appendleft((nr, nc))
        occ.add((nr, nc))
        if (nr, nc) in apples:
            apples.remove((nr, nc))
        else:
            tail = body.pop()
            occ.remove(tail)
        if ti < L and turns[ti][0] == t:
            if turns[ti][1] == "L":
                d = (d - 1) % 4
            else:
                d = (d + 1) % 4
            ti += 1


def cases_3190():
    return [
        "6\n3\n3 4\n2 5\n5 3\n3\n3 D\n15 L\n17 D\n",
        "10\n4\n1 2\n1 3\n1 4\n1 5\n4\n8 D\n10 D\n11 D\n13 L\n",
        "10\n5\n1 5\n1 3\n1 2\n1 6\n1 7\n4\n8 D\n10 D\n11 D\n13 L\n",
    ]


# 16236 아기 상어
def solve_16236():
    from collections import deque
    n = int(input())
    grid = []
    sr = sc = 0
    for i in range(n):
        row = list(map(int, input().split()))
        for j, v in enumerate(row):
            if v == 9:
                sr, sc = i, j
                row[j] = 0
        grid.append(row)
    size = 2; ate = 0; t = 0
    while True:
        # BFS find nearest eatable
        dist = [[-1] * n for _ in range(n)]
        dist[sr][sc] = 0
        q = deque([(sr, sc)])
        targets = []
        while q:
            r, c = q.popleft()
            for dr, dc in [(-1,0),(0,-1),(0,1),(1,0)]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < n and 0 <= nc < n and dist[nr][nc] == -1 and grid[nr][nc] <= size:
                    dist[nr][nc] = dist[r][c] + 1
                    if 0 < grid[nr][nc] < size:
                        targets.append((dist[nr][nc], nr, nc))
                    q.append((nr, nc))
        if not targets:
            print(t); return
        targets.sort()
        d, tr, tc = targets[0]
        t += d; ate += 1
        if ate == size:
            size += 1; ate = 0
        grid[tr][tc] = 0
        sr, sc = tr, tc


def cases_16236():
    return [
        "3\n0 0 0\n0 0 0\n0 0 9\n",
        "3\n0 0 1\n0 0 0\n0 9 0\n",
        "4\n4 3 2 1\n0 0 0 0\n0 0 9 0\n1 2 3 4\n",
        "6\n5 4 3 2 3 4\n4 3 2 3 4 5\n3 2 9 5 6 6\n2 1 2 3 4 5\n3 2 1 6 5 4\n6 6 6 6 6 6\n",
        "6\n6 0 6 0 6 1\n0 0 0 0 0 2\n2 3 4 5 6 6\n0 0 0 0 0 2\n0 2 0 0 0 0\n3 9 3 0 0 1\n",
    ]


# 16234 인구 이동
def solve_16234():
    from collections import deque
    n, l, r = map(int, input().split())
    grid = [list(map(int, input().split())) for _ in range(n)]
    days = 0
    while True:
        seen = [[False]*n for _ in range(n)]
        moved = False
        for i in range(n):
            for j in range(n):
                if seen[i][j]:
                    continue
                comp = [(i, j)]
                seen[i][j] = True
                q = deque([(i, j)])
                while q:
                    x, y = q.popleft()
                    for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < n and 0 <= ny < n and not seen[nx][ny]:
                            if l <= abs(grid[x][y] - grid[nx][ny]) <= r:
                                seen[nx][ny] = True
                                comp.append((nx, ny))
                                q.append((nx, ny))
                if len(comp) > 1:
                    avg = sum(grid[x][y] for x, y in comp) // len(comp)
                    for x, y in comp:
                        grid[x][y] = avg
                    moved = True
        if not moved:
            print(days); return
        days += 1


def cases_16234():
    return [
        "2 20 50\n50 30\n20 40\n",
        "2 40 50\n50 30\n20 40\n",
        "3 5 10\n10 15 20\n20 30 25\n40 22 10\n",
        "4 10 50\n10 100 20 90\n80 100 60 70\n70 20 30 40\n50 20 100 10\n",
    ]


# 14499 주사위 굴리기
def solve_14499():
    n, m, x, y, k = map(int, input().split())
    grid = [list(map(int, input().split())) for _ in range(n)]
    cmds = list(map(int, input().split()))
    # dice indices: top=0, bottom=1, north=2, south=3, west=4, east=5
    dice = [0]*6
    out = []
    for c in cmds:
        # 1: east, 2: west, 3: north, 4: south
        nx, ny = x, y
        if c == 1: ny += 1
        elif c == 2: ny -= 1
        elif c == 3: nx -= 1
        elif c == 4: nx += 1
        if not (0 <= nx < n and 0 <= ny < m):
            continue
        x, y = nx, ny
        t, b, n_, s, w, e = dice
        if c == 1:  # east
            dice = [w, e, n_, s, b, t]
        elif c == 2:  # west
            dice = [e, w, n_, s, t, b]
        elif c == 3:  # north
            dice = [s, n_, t, b, w, e]
        elif c == 4:  # south
            dice = [n_, s, b, t, w, e]
        if grid[x][y] == 0:
            grid[x][y] = dice[1]
        else:
            dice[1] = grid[x][y]
            grid[x][y] = 0
        out.append(str(dice[0]))
    print("\n".join(out))


def cases_14499():
    return [
        "1 2 0 0 1\n0 0\n1\n",  # only one move east
        "1 2 0 0 8\n0 0\n4 4 4 4 4 4 4 4\n",
        "3 3 1 1 9\n1 2 3\n4 0 5\n6 7 8\n1 3 2 4 1 3 2 4 1\n",
        "2 2 0 0 16\n0 2\n3 4\n1 1 2 2 3 3 4 4 1 1 2 2 3 3 4 4\n",
    ]


# 13460 구슬 탈출 2
def solve_13460():
    from collections import deque
    n, m = map(int, input().split())
    g = [list(input()) for _ in range(n)]
    rx = ry = bx = by = 0
    for i in range(n):
        for j in range(m):
            if g[i][j] == 'R': rx, ry = i, j; g[i][j] = '.'
            if g[i][j] == 'B': bx, by = i, j; g[i][j] = '.'

    def roll(x, y, dx, dy):
        cnt = 0
        while g[x + dx][y + dy] != '#' and g[x][y] != 'O':
            x += dx; y += dy; cnt += 1
        return x, y, cnt

    visited = set()
    visited.add((rx, ry, bx, by))
    q = deque([(rx, ry, bx, by, 0)])
    while q:
        rx, ry, bx, by, d = q.popleft()
        if d >= 10:
            break
        for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
            nrx, nry, rc = roll(rx, ry, dx, dy)
            nbx, nby, bc = roll(bx, by, dx, dy)
            if g[nbx][nby] == 'O':
                continue
            if g[nrx][nry] == 'O':
                print(d + 1); return
            if (nrx, nry) == (nbx, nby):
                if rc > bc:
                    nrx -= dx; nry -= dy
                else:
                    nbx -= dx; nby -= dy
            if (nrx, nry, nbx, nby) not in visited:
                visited.add((nrx, nry, nbx, nby))
                q.append((nrx, nry, nbx, nby, d + 1))
    print(-1)


def cases_13460():
    return [
        "5 5\n#####\n#..B#\n#.#.#\n#RO.#\n#####\n",
        "7 7\n#######\n#...RB#\n#.#####\n#.....#\n#####.#\n#O....#\n#######\n",
        "3 7\n#######\n#R.O.B#\n#######\n",
        "10 10\n##########\n#.O....RB#\n##########\n#........#\n#........#\n#........#\n#........#\n#........#\n#........#\n##########\n",
    ]


# 3273 두 수의 합
def solve_3273():
    n = int(input())
    a = sorted(map(int, input().split()))
    x = int(input())
    l, r = 0, n - 1
    cnt = 0
    while l < r:
        s = a[l] + a[r]
        if s == x:
            cnt += 1; l += 1; r -= 1
        elif s < x:
            l += 1
        else:
            r -= 1
    print(cnt)


def cases_3273():
    return [
        "1\n5\n5\n",
        "9\n5 12 7 10 9 1 2 3 11\n13\n",
        "5\n1 2 3 4 5\n9\n",
        _gen_3273_random(100000, 1000000),
    ]


def _gen_3273_random(n, x):
    rng = random.Random(3273)
    a = rng.sample(range(1, 1000000), n)
    return f"{n}\n{' '.join(map(str, a))}\n{x}\n"


# 2470 두 용액
def solve_2470():
    n = int(input())
    a = sorted(map(int, input().split()))
    l, r = 0, n - 1
    best = 10**18
    ans = (a[0], a[1])
    while l < r:
        s = a[l] + a[r]
        if abs(s) < best:
            best = abs(s)
            ans = (a[l], a[r])
        if s < 0: l += 1
        else: r -= 1
    print(*ans)


def cases_2470():
    return [
        "2\n-99 100\n",
        "5\n-2 4 -99 -1 98\n",
        "5\n-3 -1 0 1 3\n",  # zero exact
        _gen_2470_random(100000),
    ]


def _gen_2470_random(n):
    rng = random.Random(2470)
    a = [rng.randint(-1000000000, 1000000000) for _ in range(n)]
    return f"{n}\n{' '.join(map(str, a))}\n"


# 1644 소수의 연속합
def solve_1644():
    n = int(input())
    if n < 2:
        print(0); return
    sieve = [True] * (n + 1)
    sieve[0] = sieve[1] = False
    for i in range(2, int(n**0.5) + 1):
        if sieve[i]:
            for j in range(i*i, n + 1, i):
                sieve[j] = False
    primes = [i for i in range(2, n + 1) if sieve[i]]
    l = 0; cur = 0; cnt = 0
    for r in range(len(primes)):
        cur += primes[r]
        while cur > n:
            cur -= primes[l]; l += 1
        if cur == n:
            cnt += 1
    print(cnt)


def cases_1644():
    return [
        "1\n",
        "2\n",
        "20\n",
        "53\n",
        "100\n",
        "1000\n",
        "10000\n",
        "4000000\n",
    ]


PROBLEMS = [
    (2343, solve_2343, cases_2343),
    (6236, solve_6236, cases_6236),
    (16401, solve_16401, cases_16401),
    (14503, solve_14503, cases_14503),
    (3190, solve_3190, cases_3190),
    (16236, solve_16236, cases_16236),
    (16234, solve_16234, cases_16234),
    (14499, solve_14499, cases_14499),
    (13460, solve_13460, cases_13460),
    (3273, solve_3273, cases_3273),
    (2470, solve_2470, cases_2470),
    (1644, solve_1644, cases_1644),
]


def write_hidden_tests(pid, solver, cases):
    pdir = JUDGE / str(pid)
    if not pdir.exists():
        return 0
    for f in pdir.glob("hidden*.in"): f.unlink()
    for f in pdir.glob("hidden*.out"): f.unlink()
    written = 0
    for i, inp in enumerate(cases, 1):
        out = run_solver(solver, inp)
        (pdir / f"hidden{i}.in").write_text(inp, encoding="utf-8")
        (pdir / f"hidden{i}.out").write_text(out, encoding="utf-8")
        written += 1
    meta_path = pdir / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["hidden_count"] = written
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return written


if __name__ == "__main__":
    total = 0
    for pid, solver, gen in PROBLEMS:
        n = write_hidden_tests(pid, solver, gen())
        total += n
        print(f"  [{pid}] +{n}")
    print(f"DONE: {total} hidden cases / {len(PROBLEMS)} problems")
