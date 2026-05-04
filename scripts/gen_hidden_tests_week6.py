#!/usr/bin/env python3
"""Week 6: DP 8 + 백트래킹 4."""
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
    try:
        solver()
    finally:
        sys.stdin, sys.stdout = old
    return buf.getvalue()


# 1463 1로 만들기
def solve_1463():
    n = int(input())
    dp = [0] * (n + 1)
    for i in range(2, n + 1):
        dp[i] = dp[i - 1] + 1
        if i % 2 == 0: dp[i] = min(dp[i], dp[i // 2] + 1)
        if i % 3 == 0: dp[i] = min(dp[i], dp[i // 3] + 1)
    print(dp[n])


def cases_1463():
    return ["1\n", "2\n", "10\n", "100\n", "1000000\n", "1000\n"]


# 9095 1, 2, 3 더하기
def solve_9095():
    t = int(input())
    out = []
    dp = [0] * 12
    dp[0] = 1
    for i in range(1, 12):
        for j in (1, 2, 3):
            if i - j >= 0:
                dp[i] += dp[i - j]
    for _ in range(t):
        n = int(input())
        out.append(str(dp[n]))
    print("\n".join(out))


def cases_9095():
    return [
        "1\n1\n",
        "1\n10\n",
        "5\n1\n2\n3\n4\n5\n",
        "11\n1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n",
    ]


# 1003 피보나치 함수
def solve_1003():
    t = int(input())
    out = []
    z = [1, 0]; o = [0, 1]
    for i in range(2, 41):
        z.append(z[i-1] + z[i-2])
        o.append(o[i-1] + o[i-2])
    for _ in range(t):
        n = int(input())
        out.append(f"{z[n]} {o[n]}")
    print("\n".join(out))


def cases_1003():
    return [
        "1\n0\n",
        "1\n40\n",
        "5\n0\n1\n2\n3\n4\n",
        "10\n40\n39\n38\n37\n36\n35\n34\n33\n32\n31\n",
    ]


# 11726 2xN 타일링
def solve_11726():
    n = int(input())
    a, b = 1, 2
    if n == 1: print(1); return
    if n == 2: print(2); return
    for _ in range(n - 2):
        a, b = b, (a + b) % 10007
    print(b)


def cases_11726():
    return ["1\n", "2\n", "9\n", "1000\n", "10\n", "100\n"]


# 2579 계단 오르기
def solve_2579():
    n = int(input())
    s = [int(input()) for _ in range(n)]
    if n == 1: print(s[0]); return
    if n == 2: print(s[0] + s[1]); return
    dp = [0]*n
    dp[0] = s[0]; dp[1] = s[0] + s[1]
    dp[2] = max(s[0] + s[2], s[1] + s[2])
    for i in range(3, n):
        dp[i] = max(dp[i-2], dp[i-3] + s[i-1]) + s[i]
    print(dp[n-1])


def cases_2579():
    return [
        "1\n5\n",
        "2\n3\n7\n",
        "3\n10\n20\n30\n",
        "6\n10\n20\n15\n25\n10\n20\n",
        _gen_2579_random(300),
    ]


def _gen_2579_random(n):
    rng = random.Random(2579)
    return f"{n}\n" + "\n".join(str(rng.randint(0, 10000)) for _ in range(n)) + "\n"


# 1149 RGB거리
def solve_1149():
    n = int(input())
    rgb = [list(map(int, input().split())) for _ in range(n)]
    dp = list(rgb[0])
    for i in range(1, n):
        new = [0, 0, 0]
        new[0] = rgb[i][0] + min(dp[1], dp[2])
        new[1] = rgb[i][1] + min(dp[0], dp[2])
        new[2] = rgb[i][2] + min(dp[0], dp[1])
        dp = new
    print(min(dp))


def cases_1149():
    return [
        "1\n26 40 83\n",
        "3\n26 40 83\n49 60 57\n13 89 99\n",
        "5\n1 100 100\n100 1 100\n100 100 1\n1 100 100\n100 1 100\n",
        _gen_1149_random(1000),
    ]


def _gen_1149_random(n):
    rng = random.Random(1149)
    rows = [f"{rng.randint(1,1000)} {rng.randint(1,1000)} {rng.randint(1,1000)}" for _ in range(n)]
    return f"{n}\n" + "\n".join(rows) + "\n"


# 11053 가장 긴 증가하는 부분 수열
def solve_11053():
    from bisect import bisect_left
    n = int(input())
    a = list(map(int, input().split()))
    tails = []
    for x in a:
        i = bisect_left(tails, x)
        if i == len(tails):
            tails.append(x)
        else:
            tails[i] = x
    print(len(tails))


def cases_11053():
    return [
        "1\n1\n",
        "6\n10 20 10 30 20 50\n",
        "5\n5 4 3 2 1\n",
        "5\n1 2 3 4 5\n",
        _gen_11053_random(1000),
    ]


def _gen_11053_random(n):
    rng = random.Random(11053)
    return f"{n}\n" + " ".join(str(rng.randint(1, 1000)) for _ in range(n)) + "\n"


# 1932 정수 삼각형
def solve_1932():
    n = int(input())
    tri = [list(map(int, input().split())) for _ in range(n)]
    for i in range(1, n):
        for j in range(i + 1):
            if j == 0:
                tri[i][j] += tri[i-1][j]
            elif j == i:
                tri[i][j] += tri[i-1][j-1]
            else:
                tri[i][j] += max(tri[i-1][j-1], tri[i-1][j])
    print(max(tri[-1]))


def cases_1932():
    return [
        "1\n1\n",
        "5\n7\n3 8\n8 1 0\n2 7 4 4\n4 5 2 6 5\n",
        _gen_1932_random(500),
    ]


def _gen_1932_random(n):
    rng = random.Random(1932)
    rows = []
    for i in range(n):
        rows.append(" ".join(str(rng.randint(0, 9999)) for _ in range(i + 1)))
    return f"{n}\n" + "\n".join(rows) + "\n"


# 15649 N과 M (1)
def solve_15649():
    n, m = map(int, input().split())
    out = []
    cur = []
    used = [False] * (n + 1)
    def rec():
        if len(cur) == m:
            out.append(" ".join(map(str, cur))); return
        for i in range(1, n + 1):
            if not used[i]:
                used[i] = True; cur.append(i)
                rec()
                cur.pop(); used[i] = False
    rec()
    print("\n".join(out))


def cases_15649():
    return ["1 1\n", "3 1\n", "4 2\n", "4 4\n", "8 4\n"]


# 15650 N과 M (2)
def solve_15650():
    n, m = map(int, input().split())
    out = []
    cur = []
    def rec(start):
        if len(cur) == m:
            out.append(" ".join(map(str, cur))); return
        for i in range(start, n + 1):
            cur.append(i)
            rec(i + 1)
            cur.pop()
    rec(1)
    print("\n".join(out))


def cases_15650():
    return ["1 1\n", "3 1\n", "4 2\n", "4 4\n", "8 4\n"]


# 15652 N과 M (4)
def solve_15652():
    n, m = map(int, input().split())
    out = []
    cur = []
    def rec(start):
        if len(cur) == m:
            out.append(" ".join(map(str, cur))); return
        for i in range(start, n + 1):
            cur.append(i)
            rec(i)
            cur.pop()
    rec(1)
    print("\n".join(out))


def cases_15652():
    return ["1 1\n", "3 1\n", "3 3\n", "4 2\n", "5 3\n"]


# 9663 N-Queen
def solve_9663():
    n = int(input())
    cnt = [0]
    col = [False] * n
    d1 = [False] * (2 * n)
    d2 = [False] * (2 * n)
    def rec(r):
        if r == n:
            cnt[0] += 1; return
        for c in range(n):
            if col[c] or d1[r+c] or d2[r-c+n]: continue
            col[c] = d1[r+c] = d2[r-c+n] = True
            rec(r + 1)
            col[c] = d1[r+c] = d2[r-c+n] = False
    rec(0)
    print(cnt[0])


def cases_9663():
    return ["1\n", "4\n", "8\n", "10\n"]


PROBLEMS = [
    (1463, solve_1463, cases_1463),
    (9095, solve_9095, cases_9095),
    (1003, solve_1003, cases_1003),
    (11726, solve_11726, cases_11726),
    (2579, solve_2579, cases_2579),
    (1149, solve_1149, cases_1149),
    (11053, solve_11053, cases_11053),
    (1932, solve_1932, cases_1932),
    (15649, solve_15649, cases_15649),
    (15650, solve_15650, cases_15650),
    (15652, solve_15652, cases_15652),
    (9663, solve_9663, cases_9663),
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
