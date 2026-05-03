#!/usr/bin/env python3
"""Generate hidden test cases for Week 1 (12 problems).

For each problem:
  1) define a reference solver (verified Python implementation)
  2) define a list of test inputs covering edge / random / stress
  3) run reference solver to produce expected outputs
  4) write hidden{i}.in / hidden{i}.out files into the judge data dir
  5) bump meta.json hidden_count

Run: python3 scripts/gen_hidden_tests_week1.py
"""
from __future__ import annotations
import json
import random
import sys
from io import StringIO
from pathlib import Path
from typing import Callable, List

JUDGE = Path("/Users/tttksj/first_repo/offline_judge/data/finance/problems")

random.seed(20260427)


def run_solver(solver: Callable[[], None], stdin_text: str) -> str:
    """Run solver with given stdin, capture stdout. solver reads via input()."""
    old_stdin, old_stdout = sys.stdin, sys.stdout
    sys.stdin = StringIO(stdin_text)
    sys.stdout = buf = StringIO()
    try:
        solver()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
    return buf.getvalue()


# ---------- 1316 그룹 단어 체커 ----------
def solve_1316():
    n = int(input())
    cnt = 0
    for _ in range(n):
        w = input().strip()
        seen = set()
        ok = True
        prev = None
        for ch in w:
            if ch != prev:
                if ch in seen:
                    ok = False
                    break
                seen.add(ch)
                prev = ch
        if ok:
            cnt += 1
    print(cnt)


def cases_1316():
    return [
        # edge: N=1 single group word
        "1\na\n",
        # edge: N=1 not group word
        "1\naba\n",
        # all group words (max repetition pattern)
        "5\naabbcc\nabcabc\nxxx\nxyzxy\nooo\n",
        # mix at boundary length
        "4\n" + "a" * 100 + "\n" + "ab" * 50 + "\nz\nzz\n",
        # random 100 words
        _gen_1316_random(100),
    ]


def _gen_1316_random(n):
    rng = random.Random(1316)
    lines = [str(n)]
    for _ in range(n):
        L = rng.randint(1, 15)
        w = "".join(rng.choice("abcde") for _ in range(L))
        lines.append(w)
    return "\n".join(lines) + "\n"


# ---------- 10828 스택 ----------
def solve_10828():
    import sys as _sys
    data = _sys.stdin.read().split("\n")
    n = int(data[0])
    st = []
    out = []
    for i in range(1, n + 1):
        cmd = data[i].split()
        op = cmd[0]
        if op == "push":
            st.append(int(cmd[1]))
        elif op == "pop":
            out.append(str(st.pop() if st else -1))
        elif op == "size":
            out.append(str(len(st)))
        elif op == "empty":
            out.append("1" if not st else "0")
        elif op == "top":
            out.append(str(st[-1] if st else -1))
    print("\n".join(out))


def cases_10828():
    return [
        # edge: only empty/size on empty stack
        "5\nempty\nsize\npop\ntop\nempty\n",
        # push then pop all
        "6\npush 1\npush 2\npush 3\npop\npop\npop\n",
        # mixed ops
        "10\npush 5\npush 4\ntop\npop\nsize\nempty\npush 1\npop\npop\nempty\n",
        # large sequence (10000 mixed)
        _gen_stack_random(10000),
    ]


def _gen_stack_random(n):
    rng = random.Random(10828)
    lines = [str(n)]
    size = 0
    for _ in range(n):
        if size == 0 or rng.random() < 0.6:
            lines.append(f"push {rng.randint(1, 100000)}")
            size += 1
        else:
            op = rng.choice(["pop", "size", "empty", "top"])
            lines.append(op)
            if op == "pop":
                size -= 1
    return "\n".join(lines) + "\n"


# ---------- 2941 크로아티아 알파벳 ----------
def solve_2941():
    s = input().strip()
    croatian = ["c=", "c-", "dz=", "d-", "lj", "nj", "s=", "z="]
    for c in croatian:
        s = s.replace(c, "*")
    print(len(s))


def cases_2941():
    return [
        "a\n",  # length 1
        "ljes=njak\n",  # docs sample
        "ddz=z=\n",
        "nljj\n",
        "dz=ljnjs=z=c=c-d-\n",  # all multi-char
        "x" * 100 + "\n",  # all simple
    ]


# ---------- 4673 셀프 넘버 ----------
def solve_4673():
    not_self = set()
    for n in range(1, 10001):
        s = n + sum(int(d) for d in str(n))
        if s <= 10000:
            not_self.add(s)
    out = "\n".join(str(n) for n in range(1, 10001) if n not in not_self)
    print(out)


def cases_4673():
    return ["\n"]  # deterministic; no real hidden tests possible


# ---------- 10773 제로 ----------
def solve_10773():
    n = int(input())
    st = []
    for _ in range(n):
        x = int(input())
        if x == 0:
            if st: st.pop()
        else:
            st.append(x)
    print(sum(st))


def cases_10773():
    return [
        # only zeros (no-op since stack empty)
        "3\n0\n0\n0\n",
        # all pushes
        "4\n100\n200\n300\n400\n",
        # alternating push/pop
        "6\n1\n0\n2\n0\n3\n0\n",
        # boundary big values
        "5\n1000000\n999999\n0\n500000\n0\n",
        _gen_10773_random(10000),
    ]


def _gen_10773_random(n):
    rng = random.Random(10773)
    lines = [str(n)]
    pushed = 0
    for _ in range(n):
        if pushed == 0 or rng.random() < 0.7:
            lines.append(str(rng.randint(1, 1000000)))
            pushed += 1
        else:
            lines.append("0")
            pushed -= 1
    return "\n".join(lines) + "\n"


# ---------- 9012 괄호 ----------
def solve_9012():
    n = int(input())
    out = []
    for _ in range(n):
        s = input().strip()
        d = 0
        ok = True
        for c in s:
            d += 1 if c == "(" else -1
            if d < 0:
                ok = False
                break
        out.append("YES" if ok and d == 0 else "NO")
    print("\n".join(out))


def cases_9012():
    return [
        "1\n(\n",
        "1\n)\n",
        "2\n(())\n()()\n",
        "3\n(()\n())\n(()(()))\n",
        "1\n" + "()" * 25 + "\n",  # length 50 valid
        "1\n" + "(" * 25 + ")" * 25 + "\n",  # length 50 nested
    ]


# ---------- 1181 단어 정렬 ----------
def solve_1181():
    n = int(input())
    words = set()
    for _ in range(n):
        words.add(input().strip())
    sorted_words = sorted(words, key=lambda w: (len(w), w))
    print("\n".join(sorted_words))


def cases_1181():
    return [
        "1\nz\n",
        "5\nbb\nbb\naa\nbb\naa\n",  # all dups
        "6\nzzz\naa\naab\nz\naa\naabb\n",
        "5\napple\nbanana\ncherry\ndate\nelder\n",
        _gen_1181_random(2000),
    ]


def _gen_1181_random(n):
    rng = random.Random(1181)
    lines = [str(n)]
    for _ in range(n):
        L = rng.randint(1, 8)
        lines.append("".join(rng.choice("abcdefghij") for _ in range(L)))
    return "\n".join(lines) + "\n"


# ---------- 1427 소트인사이드 ----------
def solve_1427():
    s = input().strip()
    print("".join(sorted(s, reverse=True)))


def cases_1427():
    return [
        "0\n",
        "9\n",
        "98765\n",
        "11111\n",
        "1234567890\n",
        str(random.Random(1427).randint(10**8, 10**9 - 1)) + "\n",
    ]


# ---------- 1764 듣보잡 ----------
def solve_1764():
    n, m = map(int, input().split())
    a = set()
    for _ in range(n):
        a.add(input().strip())
    common = []
    for _ in range(m):
        x = input().strip()
        if x in a:
            common.append(x)
    common.sort()
    print(len(common))
    print("\n".join(common))


def cases_1764():
    return [
        # no overlap
        "2 2\nalice\nbob\ncarol\ndave\n",
        # full overlap
        "3 3\nalpha\nbeta\ngamma\ngamma\nalpha\nbeta\n",
        # partial
        "4 4\njohn\njane\njoe\njim\njim\njuliet\njohn\nadam\n",
        _gen_1764_random(500, 500),
    ]


def _gen_1764_random(n, m):
    rng = random.Random(1764)
    pool = ["name" + str(i) for i in range(1500)]
    a = rng.sample(pool, n)
    b = rng.sample(pool, m)
    lines = [f"{n} {m}"] + a + b
    return "\n".join(lines) + "\n"


# ---------- 2751 수 정렬하기 2 ----------
def solve_2751():
    import sys as _sys
    data = _sys.stdin.read().split()
    n = int(data[0])
    nums = sorted(map(int, data[1:n + 1]))
    _sys.stdout.write("\n".join(map(str, nums)) + "\n")


def cases_2751():
    return [
        "1\n0\n",
        "5\n5\n4\n3\n2\n1\n",
        "5\n-5\n-4\n0\n1000000\n-1000000\n",
        _gen_2751_random(5000),
    ]


def _gen_2751_random(n):
    rng = random.Random(2751)
    nums = [rng.randint(-1000000, 1000000) for _ in range(n)]
    nums = list(set(nums))  # 2751 requires distinct
    lines = [str(len(nums))] + [str(x) for x in nums]
    return "\n".join(lines) + "\n"


# ---------- 11399 ATM ----------
def solve_11399():
    n = int(input())
    p = sorted(map(int, input().split()))
    total = 0
    acc = 0
    for x in p:
        acc += x
        total += acc
    print(total)


def cases_11399():
    return [
        "1\n5\n",
        "5\n1 1 1 1 1\n",
        "5\n5 4 3 2 1\n",
        "5\n3 1 4 3 2\n",
        _gen_11399_random(1000),
    ]


def _gen_11399_random(n):
    rng = random.Random(11399)
    nums = [str(rng.randint(1, 1000)) for _ in range(n)]
    return f"{n}\n{' '.join(nums)}\n"


# ---------- 1920 수 찾기 ----------
def solve_1920():
    n = int(input())
    a = set(map(int, input().split()))
    m = int(input())
    b = list(map(int, input().split()))
    print("\n".join("1" if x in a else "0" for x in b))


def cases_1920():
    return [
        "1\n0\n1\n0\n",
        "1\n0\n1\n1\n",
        "5\n4 1 5 2 3\n5\n1 3 7 9 5\n",
        "3\n-1 0 1\n5\n-2 -1 0 1 2\n",
        _gen_1920_random(10000, 10000),
    ]


def _gen_1920_random(n, m):
    rng = random.Random(1920)
    a = [rng.randint(-1000000000, 1000000000) for _ in range(n)]
    b = [rng.choice(a) if rng.random() < 0.5 else rng.randint(-1000000000, 1000000000) for _ in range(m)]
    return f"{n}\n{' '.join(map(str, a))}\n{m}\n{' '.join(map(str, b))}\n"


# ---------- registry ----------
PROBLEMS = [
    (1316, solve_1316, cases_1316),
    (10828, solve_10828, cases_10828),
    (2941, solve_2941, cases_2941),
    (4673, solve_4673, cases_4673),
    (10773, solve_10773, cases_10773),
    (9012, solve_9012, cases_9012),
    (1181, solve_1181, cases_1181),
    (1427, solve_1427, cases_1427),
    (1764, solve_1764, cases_1764),
    (2751, solve_2751, cases_2751),
    (11399, solve_11399, cases_11399),
    (1920, solve_1920, cases_1920),
]


def write_hidden_tests(pid: int, solver, cases: List[str]) -> int:
    pdir = JUDGE / str(pid)
    if not pdir.exists():
        print(f"[SKIP] {pid} - no problem dir")
        return 0
    # remove any existing hidden files
    for f in pdir.glob("hidden*.in"):
        f.unlink()
    for f in pdir.glob("hidden*.out"):
        f.unlink()
    written = 0
    for i, inp in enumerate(cases, 1):
        out = run_solver(solver, inp)
        (pdir / f"hidden{i}.in").write_text(inp, encoding="utf-8")
        (pdir / f"hidden{i}.out").write_text(out, encoding="utf-8")
        written += 1
    # update meta.json
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
