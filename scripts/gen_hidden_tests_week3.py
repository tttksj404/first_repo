#!/usr/bin/env python3
"""Generate hidden test cases for Week 3 (12 problems): 그리디, 누적합, 이분탐색."""
from __future__ import annotations
import json, random, sys
from io import StringIO
from pathlib import Path
from typing import Callable, List

JUDGE = Path("/Users/tttksj/first_repo/offline_judge/data/finance/problems")
random.seed(20260427)


def run_solver(solver: Callable[[], None], stdin_text: str) -> str:
    old_stdin, old_stdout = sys.stdin, sys.stdout
    sys.stdin = StringIO(stdin_text)
    sys.stdout = buf = StringIO()
    try:
        solver()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
    return buf.getvalue()


# 1931 회의실 배정
def solve_1931():
    n = int(input())
    meets = [tuple(map(int, input().split())) for _ in range(n)]
    meets.sort(key=lambda x: (x[1], x[0]))
    cnt, end = 0, 0
    for s, e in meets:
        if s >= end:
            cnt += 1
            end = e
    print(cnt)


def cases_1931():
    return [
        "1\n0 1\n",
        "3\n1 1\n2 2\n3 3\n",  # zero-length meetings
        "5\n1 4\n3 5\n0 6\n5 7\n3 8\n",
        "4\n1 2\n2 3\n3 4\n4 5\n",
        _gen_1931_random(1000),
    ]


def _gen_1931_random(n):
    rng = random.Random(1931)
    lines = [str(n)]
    for _ in range(n):
        s = rng.randint(0, 10**9)
        e = s + rng.randint(0, 10**4)
        if e > 2**31 - 1:
            e = 2**31 - 1
        lines.append(f"{s} {e}")
    return "\n".join(lines) + "\n"


# 1541 잃어버린 괄호
def solve_1541():
    expr = input().strip()
    parts = expr.split("-")
    nums = [sum(int(x) for x in p.split("+")) for p in parts]
    print(nums[0] - sum(nums[1:]))


def cases_1541():
    return [
        "55-50+40\n",
        "10+20+30+40\n",
        "00009-00009\n",
        "100\n",
        "1-1-1-1-1\n",
        "9+9+9-9+9-9-9+9+9-9-9-9\n",
    ]


# 13305 주유소
def solve_13305():
    n = int(input())
    dist = list(map(int, input().split()))
    cost = list(map(int, input().split()))
    cur = cost[0]
    total = 0
    for i in range(n - 1):
        if cost[i] < cur:
            cur = cost[i]
        total += cur * dist[i]
    print(total)


def cases_13305():
    return [
        "2\n1\n5 1\n",
        "4\n2 3 1\n5 2 4 1\n",
        "5\n10 10 10 10\n1 2 3 4 5\n",
        "5\n1 1 1 1\n5 4 3 2 1\n",
        _gen_13305_random(100000),
    ]


def _gen_13305_random(n):
    rng = random.Random(13305)
    dist = [rng.randint(1, 10**9) for _ in range(n - 1)]
    cost = [rng.randint(1, 10**9) for _ in range(n)]
    return f"{n}\n{' '.join(map(str, dist))}\n{' '.join(map(str, cost))}\n"


# 16953 A → B
def solve_16953():
    a, b = map(int, input().split())
    cnt = 1
    while b > a:
        if b % 10 == 1:
            b //= 10
        elif b % 2 == 0:
            b //= 2
        else:
            print(-1); return
        cnt += 1
    print(cnt if b == a else -1)


def cases_16953():
    return [
        "2 162\n",
        "4 42\n",
        "100 40021\n",
        "1 1000000000\n",
        "999999999 1\n",  # impossible
        "1 1\n",  # already
    ]


# 11659 구간 합 구하기 4
def solve_11659():
    import sys as _sys
    data = _sys.stdin.read().split()
    idx = 0
    n = int(data[idx]); idx += 1
    m = int(data[idx]); idx += 1
    nums = list(map(int, data[idx:idx + n])); idx += n
    psum = [0] * (n + 1)
    for i, v in enumerate(nums, 1):
        psum[i] = psum[i - 1] + v
    out = []
    for _ in range(m):
        i = int(data[idx]); idx += 1
        j = int(data[idx]); idx += 1
        out.append(str(psum[j] - psum[i - 1]))
    print("\n".join(out))


def cases_11659():
    return [
        "1 1\n5\n1 1\n",
        "5 3\n5 4 3 2 1\n1 3\n2 4\n5 5\n",
        "5 5\n1 2 3 4 5\n1 1\n1 2\n1 5\n3 5\n2 4\n",
        _gen_11659_random(100000, 100000),
    ]


def _gen_11659_random(n, m):
    rng = random.Random(11659)
    nums = [rng.randint(1, 1000) for _ in range(n)]
    qs = []
    for _ in range(m):
        i = rng.randint(1, n)
        j = rng.randint(i, n)
        qs.append(f"{i} {j}")
    return f"{n} {m}\n{' '.join(map(str, nums))}\n" + "\n".join(qs) + "\n"


# 11660 구간 합 구하기 5
def solve_11660():
    import sys as _sys
    data = _sys.stdin.read().split()
    idx = 0
    n = int(data[idx]); idx += 1
    m = int(data[idx]); idx += 1
    psum = [[0] * (n + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, n + 1):
            v = int(data[idx]); idx += 1
            psum[i][j] = psum[i - 1][j] + psum[i][j - 1] - psum[i - 1][j - 1] + v
    out = []
    for _ in range(m):
        x1 = int(data[idx]); idx += 1
        y1 = int(data[idx]); idx += 1
        x2 = int(data[idx]); idx += 1
        y2 = int(data[idx]); idx += 1
        out.append(str(psum[x2][y2] - psum[x1 - 1][y2] - psum[x2][y1 - 1] + psum[x1 - 1][y1 - 1]))
    print("\n".join(out))


def cases_11660():
    return [
        "1 1\n7\n1 1 1 1\n",
        "3 3\n1 2 3\n4 5 6\n7 8 9\n1 1 3 3\n2 2 3 3\n1 2 2 3\n",
        _gen_11660_random(100, 100),
        _gen_11660_random(500, 1000),
    ]


def _gen_11660_random(n, m):
    rng = random.Random(11660)
    grid = "\n".join(" ".join(str(rng.randint(1, 1000)) for _ in range(n)) for _ in range(n))
    qs = []
    for _ in range(m):
        x1 = rng.randint(1, n); x2 = rng.randint(x1, n)
        y1 = rng.randint(1, n); y2 = rng.randint(y1, n)
        qs.append(f"{x1} {y1} {x2} {y2}")
    return f"{n} {m}\n{grid}\n" + "\n".join(qs) + "\n"


# 1806 부분합
def solve_1806():
    n, s = map(int, input().split())
    a = list(map(int, input().split()))
    l = 0
    cur = 0
    best = 10**18
    for r in range(n):
        cur += a[r]
        while cur >= s:
            best = min(best, r - l + 1)
            cur -= a[l]
            l += 1
    print(0 if best == 10**18 else best)


def cases_1806():
    return [
        "1 1\n1\n",
        "1 100\n1\n",  # impossible
        "10 15\n5 1 3 5 10 7 4 9 2 8\n",
        "5 1\n1 1 1 1 1\n",
        _gen_1806_random(100000, 100000),
    ]


def _gen_1806_random(n, s):
    rng = random.Random(1806)
    a = [rng.randint(1, 100) for _ in range(n)]
    return f"{n} {s}\n{' '.join(map(str, a))}\n"


# 2559 수열
def solve_2559():
    n, k = map(int, input().split())
    a = list(map(int, input().split()))
    cur = sum(a[:k])
    best = cur
    for i in range(k, n):
        cur += a[i] - a[i - k]
        if cur > best:
            best = cur
    print(best)


def cases_2559():
    return [
        "1 1\n5\n",
        "10 2\n3 -2 -4 -9 0 3 7 13 8 -3\n",
        "5 5\n-100 -100 -100 -100 -100\n",
        _gen_2559_random(100000, 50),
    ]


def _gen_2559_random(n, k):
    rng = random.Random(2559)
    a = [rng.randint(-100, 100) for _ in range(n)]
    return f"{n} {k}\n{' '.join(map(str, a))}\n"


# 2805 나무 자르기
def solve_2805():
    n, m = map(int, input().split())
    h = list(map(int, input().split()))
    lo, hi = 0, max(h)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        s = sum(x - mid for x in h if x > mid)
        if s >= m:
            lo = mid
        else:
            hi = mid - 1
    print(lo)


def cases_2805():
    return [
        "4 7\n20 15 10 17\n",
        "5 20\n4 42 40 26 46\n",
        "1 1\n1000000000\n",
        "3 3\n1 1 1\n",
        _gen_2805_random(1000000),
    ]


def _gen_2805_random(n):
    rng = random.Random(2805)
    h = [rng.randint(1, 1000000000) for _ in range(n)]
    m = sum(h) // 2
    return f"{n} {m}\n{' '.join(map(str, h))}\n"


# 1654 랜선 자르기
def solve_1654():
    k, n = map(int, input().split())
    cables = [int(input()) for _ in range(k)]
    lo, hi = 1, max(cables)
    while lo <= hi:
        mid = (lo + hi) // 2
        cnt = sum(c // mid for c in cables)
        if cnt >= n:
            lo = mid + 1
        else:
            hi = mid - 1
    print(hi)


def cases_1654():
    return [
        "4 11\n802\n743\n457\n539\n",
        "1 1\n1\n",
        "1 5\n10\n",
        "3 3\n1\n1\n1\n",
        _gen_1654_random(10000, 1000000),
    ]


def _gen_1654_random(k, n):
    rng = random.Random(1654)
    cables = [str(rng.randint(1, 2**31 - 1)) for _ in range(k)]
    return f"{k} {n}\n" + "\n".join(cables) + "\n"


# 2110 공유기 설치
def solve_2110():
    import sys as _sys
    data = _sys.stdin.read().split()
    n = int(data[0]); c = int(data[1])
    pos = sorted(int(x) for x in data[2:2 + n])
    lo, hi = 1, pos[-1] - pos[0]
    while lo <= hi:
        mid = (lo + hi) // 2
        cnt = 1
        last = pos[0]
        for p in pos[1:]:
            if p - last >= mid:
                cnt += 1
                last = p
        if cnt >= c:
            lo = mid + 1
        else:
            hi = mid - 1
    print(hi)


def cases_2110():
    return [
        "5 3\n1\n2\n8\n4\n9\n",
        "2 2\n0\n1000000000\n",
        "10 5\n1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n",
        _gen_2110_random(200000),
    ]


def _gen_2110_random(n):
    rng = random.Random(2110)
    pos = sorted(rng.sample(range(0, 10**9), n))
    c = rng.randint(2, n)
    return f"{n} {c}\n" + "\n".join(map(str, pos)) + "\n"


# 2512 예산
def solve_2512():
    n = int(input())
    req = list(map(int, input().split()))
    m = int(input())
    if sum(req) <= m:
        print(max(req)); return
    lo, hi = 0, max(req)
    while lo <= hi:
        mid = (lo + hi) // 2
        s = sum(min(r, mid) for r in req)
        if s <= m:
            lo = mid + 1
        else:
            hi = mid - 1
    print(hi)


def cases_2512():
    return [
        "4\n120 110 140 150\n485\n",
        "1\n100\n50\n",
        "1\n100\n200\n",
        "5\n100 100 100 100 100\n300\n",
        _gen_2512_random(10000),
    ]


def _gen_2512_random(n):
    rng = random.Random(2512)
    req = [rng.randint(1, 100000) for _ in range(n)]
    m = rng.randint(n, sum(req))
    return f"{n}\n{' '.join(map(str, req))}\n{m}\n"


PROBLEMS = [
    (1931, solve_1931, cases_1931),
    (1541, solve_1541, cases_1541),
    (13305, solve_13305, cases_13305),
    (16953, solve_16953, cases_16953),
    (11659, solve_11659, cases_11659),
    (11660, solve_11660, cases_11660),
    (1806, solve_1806, cases_1806),
    (2559, solve_2559, cases_2559),
    (2805, solve_2805, cases_2805),
    (1654, solve_1654, cases_1654),
    (2110, solve_2110, cases_2110),
    (2512, solve_2512, cases_2512),
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
        print(f"  [{pid}] +{n} hidden cases")
    print(f"DONE: {total} hidden cases written across {len(PROBLEMS)} problems")
