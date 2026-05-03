#!/usr/bin/env python3
"""Extend the finance BOJ curriculum with Week 13 supplementary problems.

Adds 11 problems covering missing topics (Heap, Bitmask, Divide & Conquer, Hash).
Updates CSV, MD, JSONL, judge index.json, and per-problem sample directories.
"""
from __future__ import annotations
import csv, json, os
from pathlib import Path

ART = Path("/Users/tttksj/first_repo/artifacts/boj_ct_curriculum_20260425_1347/finance_track")
JUDGE = Path("/Users/tttksj/first_repo/offline_judge/data/finance")

WEEK = 13
TRACK = "보강"
TYPE = "보강"

# (problem_id, topic, title, accepted, acceptance_ratio, samples [(in,out),...], description, input_spec, output_spec)
SUPPLEMENTS = [
    (1927, "우선순위 큐", "최소 힙",
     "널리 잘 알려진 자료구조 중 최소 힙이 있다. 최소 힙을 이용하여 다음과 같은 연산을 지원하는 프로그램을 작성하시오.\n1. 배열에 자연수 x를 넣는다.\n2. 배열에서 가장 작은 값을 출력하고, 그 값을 배열에서 제거한다.\n프로그램은 처음에 비어있는 배열에서 시작하게 된다.",
     "첫째 줄에 연산의 개수 N(1 ≤ N ≤ 100,000)이 주어진다. 다음 N개의 줄에는 연산에 대한 정보를 나타내는 정수 x가 주어진다. 만약 x가 자연수라면 배열에 x라는 값을 넣는 연산이고, x가 0이라면 배열에서 가장 작은 값을 출력하고 그 값을 제거하는 경우이다. x는 2^31보다 작은 자연수 또는 0이다.",
     "입력에서 0이 주어진 횟수만큼 답을 출력한다. 만약 배열이 비어 있는 경우인데 가장 작은 값을 출력하라고 한 경우에는 0을 출력하면 된다.",
     [("9\n0\n12345678\n1\n2\n0\n0\n0\n0\n32\n", "0\n1\n2\n12345678\n0\n")]),

    (11279, "우선순위 큐", "최대 힙",
     "최대 힙 자료구조를 이용한 프로그램을 작성하시오.\n1. 배열에 자연수 x를 넣는다.\n2. 배열에서 가장 큰 값을 출력하고, 그 값을 배열에서 제거한다.\n처음에 비어있는 배열에서 시작한다.",
     "첫째 줄에 연산의 개수 N(1 ≤ N ≤ 100,000). 다음 N개의 줄에 정수 x. x가 자연수면 삽입, 0이면 최댓값 출력 및 제거. x는 2^31 미만 자연수 또는 0.",
     "0이 주어진 횟수만큼 출력한다. 배열이 비어있다면 0을 출력한다.",
     [("13\n0\n1\n2\n0\n0\n3\n2\n1\n0\n0\n0\n0\n0\n", "0\n2\n1\n3\n2\n1\n0\n0\n")]),

    (11286, "우선순위 큐", "절댓값 힙",
     "절댓값 힙: 1) 정수 x(x≠0)를 배열에 추가, 2) 절댓값이 가장 작은 값을 출력하고 제거. 절댓값이 같은 값이 여럿이면 가장 작은 수를 출력한다.",
     "첫째 줄에 N(1 ≤ N ≤ 100,000). 다음 N개 줄에 정수 x. x≠0이면 추가, x=0이면 절댓값 최소값 출력 및 제거. |x| < 2^31.",
     "0이 주어진 횟수만큼 결과를 출력한다. 배열이 비어 있으면 0을 출력한다.",
     [("18\n1\n-1\n0\n0\n0\n1\n1\n-1\n-1\n2\n-2\n0\n0\n0\n0\n0\n0\n0\n", "-1\n1\n0\n-1\n-1\n1\n1\n-2\n2\n0\n")]),

    (1655, "우선순위 큐", "가운데를 말해요",
     "백준이가 외친 정수의 중간값을 말하는 프로그램. 짝수 개일 때는 두 가운데 수 중 작은 수를 말한다.",
     "첫째 줄에 백준이가 외칠 정수의 개수 N(1 ≤ N ≤ 100,000). 다음 N개의 줄에 외칠 정수(절댓값 ≤ 10,000)가 차례로 주어진다.",
     "한 줄에 하나씩 N줄에 걸쳐 동생이 말해야 하는 수를 출력한다.",
     [("7\n1\n5\n2\n10\n-99\n7\n5\n", "1\n1\n2\n2\n2\n2\n5\n")]),

    (1715, "우선순위 큐", "카드 정렬하기",
     "정렬된 두 카드 묶음을 합치려면 두 묶음 크기의 합 만큼 비교가 필요하다. N개의 묶음을 모두 합치는 데 필요한 최소 비교 횟수를 구하시오.",
     "첫째 줄에 N(1 ≤ N ≤ 100,000). 다음 N개의 줄에 카드 묶음 크기(1,000 이하 양의 정수).",
     "최소 비교 횟수를 출력한다.",
     [("3\n10\n20\n40\n", "100\n")]),

    (11723, "비트마스킹", "집합",
     "비어있는 공집합 S에 대해 다음 연산을 수행한다: add x / remove x / check x / toggle x / all / empty. (1 ≤ x ≤ 20)",
     "첫째 줄에 연산의 수 M(1 ≤ M ≤ 3,000,000). 다음 M개의 줄에 연산이 주어진다.",
     "check 연산이 주어질 때마다 1 또는 0을 출력한다.",
     [("26\nadd 1\nadd 2\ncheck 1\ncheck 2\ncheck 3\nremove 2\ncheck 1\ncheck 2\ntoggle 3\ncheck 1\ncheck 2\ncheck 3\ncheck 4\nall\ncheck 10\ncheck 20\ntoggle 10\nremove 20\ncheck 10\ncheck 20\nempty\ncheck 1\ntoggle 1\ncheck 1\ntoggle 1\ncheck 1\n",
       "1\n1\n0\n1\n0\n1\n0\n1\n0\n1\n1\n0\n0\n0\n1\n0\n")]),

    (1182, "비트마스킹", "부분수열의 합",
     "N개의 정수로 이루어진 수열에서 크기가 양수인 부분수열 중 합이 S가 되는 경우의 수를 구하라.",
     "첫째 줄에 N과 S(1 ≤ N ≤ 20, |S| ≤ 1,000,000). 둘째 줄에 N개의 정수(절댓값 ≤ 100,000).",
     "합이 S가 되는 부분수열의 개수를 출력한다.",
     [("5 0\n-7 -3 -2 5 8\n", "1\n")]),

    (1780, "분할정복", "종이의 개수",
     "N×N 종이의 각 칸에 -1, 0, 1 중 하나가 적혀 있다. 다음 규칙으로 자른다: 모두 같은 수면 그대로, 아니면 9등분 후 재귀. 각 종류 종이 개수를 구하라.",
     "첫째 줄에 N(1 ≤ N ≤ 3^7). 다음 N개의 줄에 N개의 정수.",
     "첫째 줄: -1로만 채워진 종이 수, 둘째 줄: 0, 셋째 줄: 1.",
     [("9\n0 0 0 1 1 1 -1 -1 -1\n0 0 0 1 1 1 -1 -1 -1\n0 0 0 1 1 1 -1 -1 -1\n1 1 1 0 0 0 0 0 0\n1 1 1 0 0 0 0 0 0\n1 1 1 0 0 0 0 0 0\n0 1 -1 0 1 -1 0 1 -1\n0 -1 1 0 1 -1 0 1 -1\n0 1 -1 1 0 -1 0 1 -1\n",
       "10\n12\n11\n")]),

    (1992, "분할정복", "쿼드트리",
     "흑백 영상을 쿼드트리로 압축한다. 모두 0이면 '0', 모두 1이면 '1', 아니면 4분할 후 (좌상,우상,좌하,우하) 순서로 괄호로 묶어 출력.",
     "첫째 줄에 N(1 ≤ N ≤ 64, 2의 거듭제곱). 다음 N개의 줄에 N자리 0/1 문자열.",
     "압축된 결과를 출력한다.",
     [("8\n11110000\n11110000\n00011100\n00011100\n11110000\n11110000\n11110011\n11110011\n",
       "((110(0101))(0010)1(0001))\n")]),

    (14425, "자료 구조", "문자열 집합",
     "N개의 문자열로 이루어진 집합 S에 대해, M개 문자열 중 S에 포함되는 것이 몇 개인지 구하라.",
     "첫째 줄에 N, M(1 ≤ N, M ≤ 10,000). N개의 문자열, 다음 M개의 검사할 문자열. 알파벳 소문자, 길이 ≤ 500.",
     "M개 중 S에 포함된 문자열의 개수를 출력한다.",
     [("5 11\nbaekjoononlinejudge\nstartlink\ncodeplus\nsundaycoding\ncodingsh\nbaekjoon\ncodeplus\ncodeminus\nstartlink\nstarlink\nsundaycoding\ncodingsh\ncodinghs\nsondaycoding\nstartrink\nicerink\n", "4\n")]),

    (17219, "자료 구조", "비밀번호 찾기",
     "N개의 사이트 주소와 비밀번호 쌍이 주어졌을 때, M개의 사이트 주소에 대한 비밀번호를 찾아 출력하라.",
     "첫째 줄에 N, M(1 ≤ N, M ≤ 100,000). N개의 줄에 사이트 주소와 비밀번호. 다음 M개의 줄에 조회할 사이트 주소.",
     "M개의 줄에 차례로 비밀번호를 출력한다.",
     [("16 4\nnoj.am IU\nacmicpc.net UAENA\nstartlink.io THEKINGOD\ngoogle.com ZEZE\nnate.com VOICEMAIL\nnaver.com REDQUEEN\ndaum.net MODERNTIMES\nutube.com BLACKOUT\nzum.com LASTFANTASY\ndreamwiz.com RAINDROP\nhanyang.ac.kr SOMEDAY\ndhlottery.co.kr BOO\nduksoo.hs.kr HAVANA\nhanyang-u.ms.kr OBLIVIATE\nyd.es.kr LOVEATTACK\nmcc.hanyang.ac.kr ADREAMER\nstartlink.io\nacmicpc.net\nnoj.am\nmcc.hanyang.ac.kr\n", "THEKINGOD\nUAENA\nIU\nADREAMER\n")]),
]


def update_csv() -> None:
    csv_path = ART / "boj_finance_problem_pack.csv"
    rows = list(csv.DictReader(open(csv_path)))
    fieldnames = list(rows[0].keys())
    existing_ids = {r["problem_id"] for r in rows}
    for pid, topic, title, *_ , samples in [(s[0], s[1], s[2], s[3], s[4], s[5], s[6]) for s in SUPPLEMENTS]:
        pass  # placeholder
    for s in SUPPLEMENTS:
        pid = str(s[0])
        if pid in existing_ids:
            continue
        rows.append({
            "week": str(WEEK),
            "track": TRACK,
            "type": TYPE,
            "topic": s[1],
            "problem_id": pid,
            "title": s[2],
            "url": f"https://www.acmicpc.net/problem/{pid}",
            "accepted": "",
            "acceptance_ratio": "",
        })
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"CSV: {len(rows)} rows")


def update_jsonl() -> None:
    jsonl_path = ART / "boj_finance_problem_texts.jsonl"
    with open(jsonl_path) as f:
        lines = [json.loads(l) for l in f]
    existing = {r["problem_id"] for r in lines}
    for s in SUPPLEMENTS:
        pid = s[0]
        if pid in existing:
            continue
        sample_in = [io[0] for io in s[6]]
        sample_out = [io[1] for io in s[6]]
        lines.append({
            "week": WEEK,
            "track": TRACK,
            "topic": s[1],
            "problem_id": pid,
            "title": s[2],
            "url": f"https://www.acmicpc.net/problem/{pid}",
            "description": s[3],
            "input": s[4],
            "output": s[5],
            "sample_inputs": sample_in,
            "sample_outputs": sample_out,
        })
    with open(jsonl_path, "w") as f:
        for r in lines:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"JSONL: {len(lines)} rows")


def update_md() -> None:
    md_path = ART / "boj_finance_curriculum.md"
    text = md_path.read_text()
    if "## Week 13" in text:
        print("MD: Week 13 already present, skipping")
        return
    # group by topic
    from collections import defaultdict
    by_topic = defaultdict(list)
    for s in SUPPLEMENTS:
        by_topic[s[1]].append(s)
    topic_summary = ", ".join(f"{t} {len(items)}문제" for t, items in by_topic.items())
    block = [f"\n## Week 13 - 보강 트랙 (빈출 토픽 보강)\n",
             f"- 주제 구성: {topic_summary}",
             f"- 추가 사유: 우선순위 큐/비트마스킹/분할정복/해시 테이블 — 금융권 코테 빈출이지만 1~12주차 누락",
             "- 문제 목록:"]
    for s in SUPPLEMENTS:
        block.append(f"  - [{s[0]} {s[2]}](https://www.acmicpc.net/problem/{s[0]}) [보강, {s[1]}]")
    block.append("")
    new_text = text.rstrip() + "\n" + "\n".join(block) + "\n"
    # update total count
    new_text = new_text.replace("총 문제 수: **160**", "총 문제 수: **171**")
    md_path.write_text(new_text)
    print("MD updated")


def update_judge() -> None:
    idx_path = JUDGE / "index.json"
    idx = json.loads(idx_path.read_text())
    existing = {p["problem_id"] for p in idx["problems"]}
    probs_dir = JUDGE / "problems"
    for s in SUPPLEMENTS:
        pid = s[0]
        pdir = probs_dir / str(pid)
        pdir.mkdir(exist_ok=True)
        meta = {
            "problem_id": pid, "week": WEEK, "topic": s[1], "title": s[2],
            "url": f"https://www.acmicpc.net/problem/{pid}",
            "sample_count": len(s[6]),
        }
        (pdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        for i, (inp, out) in enumerate(s[6], start=1):
            (pdir / f"sample{i}.in").write_text(inp)
            (pdir / f"sample{i}.out").write_text(out)
        if pid not in existing:
            idx["problems"].append(meta)
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2))
    print(f"Judge index: {len(idx['problems'])} problems")


if __name__ == "__main__":
    update_csv()
    update_jsonl()
    update_md()
    update_judge()
    print("DONE")
