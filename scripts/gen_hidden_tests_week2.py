#!/usr/bin/env python3
"""Generate hidden test cases for Week 2 (12 problems)."""
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


# 1018 체스판 다시 칠하기
def solve_1018():
    n, m = map(int, input().split())
    board = [input().strip() for _ in range(n)]
    best = 10**9
    for r in range(n - 7):
        for c in range(m - 7):
            for first in "WB":
                cnt = 0
                for i in range(8):
                    for j in range(8):
                        exp = first if (i + j) % 2 == 0 else ("B" if first == "W" else "W")
                        if board[r + i][c + j] != exp:
                            cnt += 1
                if cnt < best:
                    best = cnt
    print(best)


def cases_1018():
    return [
        # 8x8 already perfect WBWB pattern
        "8 8\n" + "\n".join("WBWBWBWB" if i % 2 == 0 else "BWBWBWBW" for i in range(8)) + "\n",
        # 8x8 inverse pattern
        "8 8\n" + "\n".join("BWBWBWBW" if i % 2 == 0 else "WBWBWBWB" for i in range(8)) + "\n",
        # 8x8 all white (max repaint)
        "8 8\n" + "\n".join("WWWWWWWW" for _ in range(8)) + "\n",
        # 10x13 mixed
        _gen_1018_random(10, 13, 1018),
        _gen_1018_random(50, 50, 1019),
    ]


def _gen_1018_random(n, m, seed):
    rng = random.Random(seed)
    rows = ["".join(rng.choice("WB") for _ in range(m)) for _ in range(n)]
    return f"{n} {m}\n" + "\n".join(rows) + "\n"


# 1436 영화감독 숌
def solve_1436():
    n = int(input())
    cnt, x = 0, 665
    while cnt < n:
        x += 1
        if "666" in str(x):
            cnt += 1
    print(x)


def cases_1436():
    return ["1\n", "2\n", "3\n", "100\n", "5000\n", "10000\n"]


# 7568 덩치
def solve_7568():
    n = int(input())
    p = [tuple(map(int, input().split())) for _ in range(n)]
    out = []
    for i in range(n):
        rank = 1
        for j in range(n):
            if i != j and p[j][0] > p[i][0] and p[j][1] > p[i][1]:
                rank += 1
        out.append(str(rank))
    print(" ".join(out))


def cases_7568():
    return [
        "1\n55 185\n",
        "3\n55 185\n55 185\n55 185\n",
        "5\n55 185\n58 183\n88 186\n60 175\n46 155\n",
        _gen_7568_random(50),
    ]


def _gen_7568_random(n):
    rng = random.Random(7568)
    lines = [str(n)]
    for _ in range(n):
        lines.append(f"{rng.randint(40, 120)} {rng.randint(140, 200)}")
    return "\n".join(lines) + "\n"


# 14501 퇴사
def solve_14501():
    n = int(input())
    t = [0] * (n + 1)
    p = [0] * (n + 1)
    for i in range(1, n + 1):
        t[i], p[i] = map(int, input().split())
    dp = [0] * (n + 2)
    for i in range(n, 0, -1):
        if i + t[i] > n + 1:
            dp[i] = dp[i + 1]
        else:
            dp[i] = max(dp[i + 1], p[i] + dp[i + t[i]])
    print(dp[1])


def cases_14501():
    return [
        # N=1 doable
        "1\n1 100\n",
        # N=1 not doable (t > N)
        "1\n2 100\n",
        # all t=1
        "5\n1 10\n1 20\n1 30\n1 40\n1 50\n",
        # large t blocking
        "7\n3 10\n5 20\n1 10\n1 20\n2 15\n4 40\n2 200\n",
        _gen_14501_random(15),
    ]


def _gen_14501_random(n):
    rng = random.Random(14501)
    lines = [str(n)]
    for _ in range(n):
        lines.append(f"{rng.randint(1, 5)} {rng.randint(1, 1000)}")
    return "\n".join(lines) + "\n"


# 2839 설탕 배달
def solve_2839():
    n = int(input())
    for k5 in range(n // 5, -1, -1):
        rem = n - 5 * k5
        if rem % 3 == 0:
            print(k5 + rem // 3)
            return
    print(-1)


def cases_2839():
    return ["3\n", "4\n", "5\n", "6\n", "7\n", "8\n", "11\n", "5000\n", "1\n", "2\n"]


# 1929 소수 구하기
def solve_1929():
    m, n = map(int, input().split())
    sieve = [True] * (n + 1)
    sieve[0] = sieve[1] = False
    for i in range(2, int(n ** 0.5) + 1):
        if sieve[i]:
            for j in range(i * i, n + 1, i):
                sieve[j] = False
    print("\n".join(str(i) for i in range(m, n + 1) if sieve[i]))


def cases_1929():
    return [
        "1 1\n",
        "1 2\n",
        "2 2\n",
        "10 100\n",
        "1 1000\n",
        "999900 1000000\n",
    ]


# 1065 한수
def solve_1065():
    n = int(input())
    cnt = 0
    for x in range(1, n + 1):
        d = list(map(int, str(x)))
        if len(d) <= 2 or all(d[i + 1] - d[i] == d[1] - d[0] for i in range(len(d) - 1)):
            cnt += 1
    print(cnt)


def cases_1065():
    return ["1\n", "10\n", "99\n", "100\n", "210\n", "1000\n"]


# 2164 카드2
def solve_2164():
    from collections import deque
    n = int(input())
    q = deque(range(1, n + 1))
    while len(q) > 1:
        q.popleft()
        q.append(q.popleft())
    print(q[0])


def cases_2164():
    return ["1\n", "2\n", "3\n", "6\n", "100\n", "500000\n"]


# 10845 큐
def solve_10845():
    import sys as _sys
    from collections import deque
    data = _sys.stdin.read().split("\n")
    n = int(data[0])
    q = deque()
    out = []
    for i in range(1, n + 1):
        cmd = data[i].split()
        op = cmd[0]
        if op == "push":
            q.append(int(cmd[1]))
        elif op == "pop":
            out.append(str(q.popleft() if q else -1))
        elif op == "size":
            out.append(str(len(q)))
        elif op == "empty":
            out.append("1" if not q else "0")
        elif op == "front":
            out.append(str(q[0] if q else -1))
        elif op == "back":
            out.append(str(q[-1] if q else -1))
    print("\n".join(out))


def cases_10845():
    return [
        "5\nempty\nsize\nfront\nback\npop\n",
        "6\npush 1\npush 2\npush 3\nfront\nback\nsize\n",
        "10\npush 1\npush 2\npop\npush 3\nfront\nback\npop\npop\nempty\npop\n",
        _gen_queue_random(5000),
    ]


def _gen_queue_random(n):
    rng = random.Random(10845)
    lines = [str(n)]
    size = 0
    for _ in range(n):
        if size == 0 or rng.random() < 0.5:
            lines.append(f"push {rng.randint(1, 100000)}")
            size += 1
        else:
            op = rng.choice(["pop", "size", "empty", "front", "back"])
            lines.append(op)
            if op == "pop":
                size -= 1
    return "\n".join(lines) + "\n"


# 10816 숫자 카드 2
def solve_10816():
    from collections import Counter
    input()
    a = Counter(map(int, input().split()))
    input()
    b = list(map(int, input().split()))
    print(" ".join(str(a.get(x, 0)) for x in b))


def cases_10816():
    return [
        "1\n0\n1\n0\n",
        "5\n6 3 2 10 10\n3\n10 9 -5\n",
        "3\n1 1 1\n3\n1 1 2\n",
        _gen_10816_random(10000, 10000),
    ]


def _gen_10816_random(n, m):
    rng = random.Random(10816)
    a = [rng.randint(-10000, 10000) for _ in range(n)]
    b = [rng.choice(a) if rng.random() < 0.5 else rng.randint(-10000, 10000) for _ in range(m)]
    return f"{n}\n{' '.join(map(str, a))}\n{m}\n{' '.join(map(str, b))}\n"


# 1874 스택 수열
def solve_1874():
    import sys as _sys
    data = _sys.stdin.read().split()
    n = int(data[0])
    target = list(map(int, data[1:n + 1]))
    stack, ops, cur = [], [], 1
    ok = True
    for t in target:
        while cur <= t:
            stack.append(cur)
            ops.append("+")
            cur += 1
        if stack and stack[-1] == t:
            stack.pop()
            ops.append("-")
        else:
            ok = False
            break
    if ok:
        print("\n".join(ops))
    else:
        print("NO")


def cases_1874():
    return [
        "1\n1\n",
        "3\n1 2 3\n",
        "3\n3 2 1\n",
        "5\n1 2 5 3 4\n",  # NO case
        _gen_1874_random(2000),
    ]


def _gen_1874_random(n):
    rng = random.Random(1874)
    seq = list(range(1, n + 1))
    rng.shuffle(seq)
    return f"{n}\n" + "\n".join(map(str, seq)) + "\n"


# 11866 요세푸스 0
def solve_11866():
    from collections import deque
    n, k = map(int, input().split())
    q = deque(range(1, n + 1))
    out = []
    while q:
        q.rotate(-(k - 1))
        out.append(str(q.popleft()))
    print(f"<{', '.join(out)}>")


def cases_11866():
    return ["1 1\n", "7 3\n", "10 1\n", "5 5\n", "1000 7\n"]


PROBLEMS = [
    (1018, solve_1018, cases_1018),
    (1436, solve_1436, cases_1436),
    (7568, solve_7568, cases_7568),
    (14501, solve_14501, cases_14501),
    (2839, solve_2839, cases_2839),
    (1929, solve_1929, cases_1929),
    (1065, solve_1065, cases_1065),
    (2164, solve_2164, cases_2164),
    (10845, solve_10845, cases_10845),
    (10816, solve_10816, cases_10816),
    (1874, solve_1874, cases_1874),
    (11866, solve_11866, cases_11866),
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
