#!/usr/bin/env python3
"""Add Week 14 — IT/전산직 advanced track (10 problems).

Topics: 플로이드-워셜, 세그먼트 트리, 배낭 DP, LCS, 트라이, KMP, LCA.
"""
from __future__ import annotations
import csv, json
from pathlib import Path

ART = Path("/Users/tttksj/first_repo/artifacts/boj_ct_curriculum_20260425_1347/finance_track")
JUDGE = Path("/Users/tttksj/first_repo/offline_judge/data/finance")

WEEK = 14
TRACK = "전산직심화"
TYPE = "심화"

# (pid, topic, title, description, input_spec, output_spec, [(in,out),...])
SUPPLEMENTS = [
    (11404, "플로이드-워셜", "플로이드",
     "n(2 ≤ n ≤ 100)개의 도시와 한 도시에서 다른 도시로 가는 m(1 ≤ m ≤ 100,000)개의 버스가 있다. 모든 도시 쌍 (A, B)에 대해 A에서 B로 가는 데 필요한 비용의 최솟값을 구하라. 같은 (A,B) 노선이 여러 개일 수 있다.",
     "첫째 줄에 도시의 개수 n, 둘째 줄에 버스의 개수 m. 다음 m줄에 시작도시 a, 도착도시 b, 비용 c(≤ 100,000). 시작과 도착이 같은 경우는 없다.",
     "n×n 행렬을 출력한다. i행 j열에 i→j 최소비용. 갈 수 없으면 0.",
     [("5\n14\n1 2 2\n1 3 3\n1 4 1\n1 5 10\n2 4 2\n3 4 1\n3 5 1\n4 5 3\n3 5 10\n3 1 8\n1 4 2\n5 1 7\n3 4 2\n5 2 4\n",
       "0 2 3 1 4\n12 0 15 2 5\n8 5 0 1 1\n10 7 13 0 3\n7 4 10 6 0\n")]),

    (11403, "플로이드-워셜", "경로 찾기",
     "가중치 없는 방향 그래프 G가 있다. 모든 정점 (i, j)에 대해 i에서 j로 가는 길이가 양수인 경로가 있는지 구하라.",
     "첫째 줄에 정점 개수 N(1 ≤ N ≤ 100). 다음 N줄에 인접행렬. i행 j열이 1이면 i→j 간선 존재. 자기 간선은 항상 0.",
     "N×N 인접행렬. i→j 양수 길이 경로가 있으면 1, 없으면 0.",
     [("3\n0 1 0\n0 0 1\n1 0 0\n", "1 1 1\n1 1 1\n1 1 1\n")]),

    (2042, "세그먼트 트리", "구간 합 구하기",
     "N개의 수가 있고, 중간에 수의 변경이 자주 일어난다. 변경과 구간 합 쿼리를 처리하라.",
     "첫째 줄에 N(1 ≤ N ≤ 1,000,000), M(1 ≤ M ≤ 10,000), K(1 ≤ K ≤ 10,000). M은 변경 횟수, K는 구간 합 횟수. 다음 N줄에 수. 다음 M+K줄에 a b c. a=1: b번째를 c로 변경. a=2: b부터 c까지 합 출력.",
     "K줄에 걸쳐 구간 합 출력.",
     [("5 2 2\n1\n2\n3\n4\n5\n1 3 6\n2 2 5\n1 5 2\n2 3 5\n", "17\n12\n")]),

    (11505, "세그먼트 트리", "구간 곱 구하기",
     "N개의 수에 대해 변경 또는 구간 곱 쿼리를 처리하라. 곱은 1,000,000,007로 나눈 나머지.",
     "첫째 줄: N(1 ≤ N ≤ 1,000,000), M(1 ≤ M ≤ 10,000), K(1 ≤ K ≤ 10,000). 다음 N줄에 수(1 이상 1,000,000,000 이하 자연수). 다음 M+K줄에 a b c. a=1: b번째를 c로 변경. a=2: b부터 c까지 곱.",
     "K줄에 걸쳐 구간 곱 mod 1,000,000,007 출력.",
     [("5 2 2\n1\n2\n3\n4\n5\n1 3 6\n2 2 5\n1 5 2\n2 3 5\n", "240\n48\n")]),

    (12865, "배낭 DP", "평범한 배낭",
     "N개 물건이 있고 각각 무게 W와 가치 V를 가진다. 배낭은 최대 K 무게까지 담을 수 있다. 배낭에 담을 수 있는 가치의 최대 합을 구하라.",
     "첫째 줄에 N(1 ≤ N ≤ 100)과 K(1 ≤ K ≤ 100,000). 다음 N줄에 무게 W(1 ≤ W ≤ 100,000)와 가치 V(0 ≤ V ≤ 1,000).",
     "최대 가치 합을 출력.",
     [("4 7\n6 13\n4 8\n3 6\n5 12\n", "14\n")]),

    (2293, "배낭 DP", "동전 1",
     "n가지 동전이 있다. 동전을 사용해 합이 k가 되도록 하는 경우의 수를 구하라. 각 동전은 무한히 사용 가능. 순서가 다른 같은 구성은 같은 경우.",
     "첫째 줄에 n, k(1 ≤ n ≤ 100, 1 ≤ k ≤ 10,000). 다음 n줄에 동전 가치(자연수, ≤ 100,000). 동전 가치는 중복될 수 있음.",
     "경우의 수를 출력. 답은 2^31 미만.",
     [("3 10\n1\n2\n5\n", "10\n")]),

    (9251, "DP", "LCS",
     "두 수열이 주어졌을 때, 모두의 부분수열이 되는 수열 중 가장 긴 것을 구하라.",
     "첫째 줄과 둘째 줄에 두 문자열. 알파벳 대문자, 길이 ≤ 1000.",
     "LCS의 길이를 출력.",
     [("ACAYKP\nCAPCAK\n", "4\n")]),

    (5052, "트라이", "전화번호 목록",
     "전화번호 목록이 일관성 있는지 판별하라. 어떤 번호도 다른 번호의 접두어가 되지 않으면 일관성 있음.",
     "첫째 줄에 테스트 케이스 t(1 ≤ t ≤ 50). 각 케이스 첫줄에 n(1 ≤ n ≤ 10,000). 다음 n줄에 전화번호(서로 다름, 길이 ≤ 10).",
     "각 케이스마다 일관성 있으면 YES, 없으면 NO.",
     [("2\n3\n911\n97625999\n91125426\n5\n113\n12340\n123440\n12345\n98346\n", "NO\nYES\n")]),

    (1786, "KMP", "찾기",
     "워드프로세서의 찾기 기능을 구현하라. 텍스트 T 안에서 패턴 P가 몇 번 등장하는지, 어느 위치에서 등장하는지 구하라.",
     "첫째 줄에 문자열 T, 둘째 줄에 P. 길이 1~1,000,000. 알파벳 대소문자와 공백.",
     "첫째 줄에 등장 횟수, 둘째 줄에 등장 위치(1-indexed) 공백 구분.",
     [("ABC ABCDAB ABCDABCDABDE\nABCDABD\n", "1\n16\n")]),

    (11437, "LCA", "LCA",
     "N개 정점 트리에서, 두 노드의 가장 가까운 공통 조상을 구하라. 루트는 1번.",
     "첫째 줄에 N(2 ≤ N ≤ 50,000). 다음 N-1줄에 트리 간선. 다음 줄에 쿼리 수 M(1 ≤ M ≤ 10,000). 다음 M줄에 두 노드.",
     "M줄에 차례로 LCA를 출력.",
     [("15\n1 2\n1 3\n2 4\n3 7\n6 2\n3 8\n4 9\n2 5\n5 11\n7 13\n10 4\n11 15\n12 5\n14 7\n6\n6 11\n10 9\n2 6\n7 6\n8 13\n8 15\n",
       "2\n4\n2\n1\n3\n1\n")]),
]


def update_csv():
    csv_path = ART / "boj_finance_problem_pack.csv"
    rows = list(csv.DictReader(open(csv_path)))
    fieldnames = list(rows[0].keys())
    existing = {r["problem_id"] for r in rows}
    for s in SUPPLEMENTS:
        pid = str(s[0])
        if pid in existing:
            continue
        rows.append({
            "week": str(WEEK), "track": TRACK, "type": TYPE,
            "topic": s[1], "problem_id": pid, "title": s[2],
            "url": f"https://www.acmicpc.net/problem/{pid}",
            "accepted": "", "acceptance_ratio": "",
        })
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader(); w.writerows(rows)
    print(f"CSV: {len(rows)}")


def update_jsonl():
    p = ART / "boj_finance_problem_texts.jsonl"
    lines = [json.loads(l) for l in open(p)]
    existing = {r["problem_id"] for r in lines}
    for s in SUPPLEMENTS:
        if s[0] in existing:
            continue
        lines.append({
            "week": WEEK, "track": TRACK, "topic": s[1],
            "problem_id": s[0], "title": s[2],
            "url": f"https://www.acmicpc.net/problem/{s[0]}",
            "description": s[3], "input": s[4], "output": s[5],
            "sample_inputs": [io[0] for io in s[6]],
            "sample_outputs": [io[1] for io in s[6]],
        })
    with open(p, "w") as f:
        for r in lines:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"JSONL: {len(lines)}")


def update_md():
    p = ART / "boj_finance_curriculum.md"
    text = p.read_text()
    if "## Week 14" in text:
        print("MD: Week 14 already present")
        return
    from collections import defaultdict
    by_topic = defaultdict(list)
    for s in SUPPLEMENTS:
        by_topic[s[1]].append(s)
    summary = ", ".join(f"{t} {len(v)}문제" for t, v in by_topic.items())
    block = [f"\n## Week 14 - 전산직 심화 트랙\n",
             f"- 주제 구성: {summary}",
             "- 추가 사유: 카카오뱅크/토스/네이버파이낸셜/우리에프아이에스/KB데이타시스템/신한DS/하나금융티아이 등 금융권 전산직 코테 빈출 영역 보강",
             "- 문제 목록:"]
    for s in SUPPLEMENTS:
        block.append(f"  - [{s[0]} {s[2]}](https://www.acmicpc.net/problem/{s[0]}) [심화, {s[1]}]")
    block.append("")
    new_text = text.rstrip() + "\n" + "\n".join(block) + "\n"
    new_text = new_text.replace("총 문제 수: **171**", "총 문제 수: **181**")
    p.write_text(new_text)
    print("MD updated")


def update_judge():
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
    print(f"Judge index: {len(idx['problems'])}")


if __name__ == "__main__":
    update_csv()
    update_jsonl()
    update_md()
    update_judge()
    print("DONE")
