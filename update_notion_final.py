# -*- coding: utf-8 -*-
import requests
import json

TOKEN = "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"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

UPDATE_LIST = [
    {"id": "2feeacc8-175a-80ee-9739-cb395ef4cc64", "key": "Greedy"},
    {"id": "302eacc8-175a-8072-aad8-db2ca96b67e4", "key": "DP"},
    {"id": "2f0eacc8-175a-8072-8e4b-e298edcb69c5", "key": "DFS"},
    {"id": "2fceacc8-175a-8049-a889-f4dfad72a7de", "key": "Simulation"}
]

ALGO_DATA = {
    "Greedy": {
        "title": "탐욕 알고리즘 (Greedy) & 파라메트릭 서치",
        "intro": "현재 상황에서 가장 최선의 선택을 하는 알고리즘. '정당성 증명'이 핵심이며, 파라메트릭 서치와 자주 결합됩니다.",
        "mechanism": "1. 단계별 최선 선택\n2. 제약 조건 확인\n3. 결정 문제(Yes/No)로 변환하여 이분 탐색",
        "code": "while start <= end:\n    mid = (start + end) // 2\n    if check(mid): result = mid; start = mid + 1\n    else: end = mid - 1",
        "tips": "10162: 수학적 규칙성 찾기\n2805: '적어도 M만큼' 조건은 파라메트릭 서치"
    },
    "DP": {
        "title": "다이나믹 프로그래밍 (DP)",
        "intro": "작은 문제의 결과를 저장(Memoization)하여 큰 문제를 해결하는 최적화 기법.",
        "mechanism": "1. 점화식 도출\n2. Memoization (Top-Down/Bottom-Up)\n3. 초기값 설정",
        "code": "dp = [0] * (N + 1)\nfor i in range(2, N + 1):\n    dp[i] = (dp[i-1] + dp[i-2]) % MOD",
        "tips": "15624: 공간 복잡도 최적화 (변수 2개만 사용)"
    },
    "DFS": {
        "title": "DFS & 백트래킹 (Backtracking)",
        "intro": "모든 경우의 수를 탐색하되, 조건에 맞지 않으면 되돌아오는 기법. 순열/조합 구현의 핵심.",
        "mechanism": "1. 방문 처리\n2. 재귀 호출\n3. 상태 복구 (visited[i] = False)",
        "code": "def backtrack(depth):\n    if depth == M: return\n    for i in range(N):\n        if not visited[i]:\n            visited[i] = True; backtrack(depth + 1); visited[i] = False",
        "tips": "2667: 단지 번호 붙이기 (탐색 후 결과 정렬)\n상태 복구를 잊지 말 것!"
    },
    "Simulation": {
        "title": "시뮬레이션 & 2차원 배열 탐색",
        "intro": "격자판 위에서의 이동, 회전, 중력 등을 구현하는 능력. 델타 탐색이 기본입니다.",
        "mechanism": "1. 델타 탐색 (dr, dc)\n2. 배열 범위 체크\n3. 격자 회전 및 복사",
        "code": "rotated = [list(row) for row in zip(*matrix[::-1])]",
        "tips": "10157(달팽이): 방향 전환 로직\n21862: 단계별 함수화(move, rotate)"
    }
}

def delete_blocks(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    res = requests.get(url, headers=HEADERS).json()
    for block in res.get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{block['id']}", headers=HEADERS)

def update_page(page_id, key):
    delete_blocks(page_id)
    content = ALGO_DATA[key]
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    payload = {
        "children": [
            {"object": "block", "type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": content['title']}}]}},
            {"object": "block", "type": "callout", "callout": {"rich_text": [{"text": {"content": content['intro']}}], "icon": {"emoji": "🚀"}}},
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🔍 메커니즘 (Mechanism)"}}]}},
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": content['mechanism']}}]}},
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "💻 핵심 코드 스니펫"}}]}},
            {"object": "block", "type": "code", "code": {"language": "python", "rich_text": [{"text": {"content": content['code']}}]}},
            {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "💡 실전 문제 풀이 팁"}}]}},
            {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": content['tips']}}]}}
        ]
    }
    requests.patch(url, json=payload, headers=HEADERS)
    print(f"Updated: {key}")

if __name__ == "__main__":
    for item in UPDATE_LIST:
        update_page(item['id'], item['key'])
