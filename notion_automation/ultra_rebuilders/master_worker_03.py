import requests
import json
import time


import os

def _get_notion_token():
    # Try multiple paths to find notion_key.txt
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(current_dir, 'notion_key.txt'),
        os.path.join(current_dir, '..', 'core', 'notion_key.txt'),
        os.path.join(current_dir, 'core', 'notion_key.txt'),
        os.path.join(os.getcwd(), 'notion_automation', 'core', 'notion_key.txt')
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                token = f.read().strip()
                if token: return token
    return os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")

NOTION_TOKEN = _get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def rebuild_one_perfectly(pid, title, blocks):
    print(f"--- [ULTRA-DEEP REBUILD] {title} ---")
    # 1. Clear existing
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.05)
    
    # 2. Patch in chunks (3 blocks each for stability)
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        res = requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": chunk})
        if res.status_code != 200:
            print(f"FAILED on chunk {i//3 + 1}: {res.text}")
            return False
        time.sleep(1)
    
    # 3. Final Count Verification
    res_verify = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    actual_count = len(res_verify.json().get("results", []))
    print(f"VERIFIED: {title} now has {actual_count} blocks.")
    return True

# --------------------------------------------------------------------------------
# Problem 03 - 스타트와 링크 (Full Version)
# --------------------------------------------------------------------------------
link_full_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 03] 스타트와 링크 - 백트래킹 기반 팀 매칭 최적화"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "문제 상황: N명의 사람을 N/2명씩 두 팀으로 나누어, 각 팀의 능력치 합의 차이가 최소가 되도록 팀을 구성해야 합니다. 팀워크(S[i][j])는 두 사람이 같은 팀일 때만 발휘되며, 모든 경우의 수를 탐색해야 하는 백트래킹 문제입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석 (Constraints)"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "인원 구성: 총 N명(N은 짝수, 최대 20). 스타트 팀 N/2명, 링크 팀 N/2명으로 정확히 나눕니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "능력치 계산: S[i][j]와 S[j][i]는 다를 수 있으며, i번과 j번이 같은 팀이면 두 값을 모두 더해야 합니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "content": {"content": "탐색 범위: 20C10은 약 18만으로, 백트래킹(DFS) 전수 조사가 충분히 가능한 범위입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계 (Logic)"}}]}},
    {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "현실의 생각: ", "annotations": {"bold": True}}, {"type": "text", "text": "모든 멤버 중 절반을 한 팀으로 뽑아보자. 뽑히지 않은 나머지 절반은 자동으로 상대 팀이 된다. 이렇게 모든 조합을 다 짜보고 실력 차이가 가장 적은 대진표를 고르면 된다!"}}]}},
    {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "코딩의 생각: ", "annotations": {"bold": True}}, {"type": "text", "text": "DFS(idx, count)를 호출한다. idx는 현재 고려 중인 멤버 번호, count는 스타트 팀에 영입된 인원이다. count가 N/2가 되는 순간 '재귀의 끝'에 도달하며, 이때 visited가 True인 사람과 False인 사람으로 나누어 점수를 계산한다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🏗️ 3. 구현 필수 체크리스트 (IM 스타일)"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "0번 멤버 고정 최적화: 팀 구성은 대칭적이므로, 0번 멤버를 항상 스타트 팀에 넣는다고 고정하면 연산 횟수를 50% 줄일 수 있습니다."}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "능력치 합산 로직: 팀원 확정 후 2중 for문으로 S[i][j]와 S[j][i]를 빠짐없이 더했는지 인덱스 설계를 확인하세요."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 4. Python 전체 정답 코드 (Full Version)"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''import sys

def dfs(idx, count):
    global min_diff
    # 1. 기저 사례: 한 팀의 인원이 N/2명이 되었을 때
    if count == N // 2:
        start_score, link_score = 0, 0
        for i in range(N):
            for j in range(N):
                # i와 j가 둘 다 True면 스타트 팀
                if visited[i] and visited[j]:
                    start_score += S[i][j]
                # i와 j가 둘 다 False면 링크 팀
                elif not visited[i] and not visited[j]:
                    link_score += S[i][j]
        
        # 두 팀의 능력치 차이 최솟값 갱신
        min_diff = min(min_diff, abs(start_score - link_score))
        return

    # 2. 유도 파트: 현재 idx부터 멤버를 팀에 넣을지 결정
    for i in range(idx, N):
        if not visited[i]:
            visited[i] = True
            dfs(i + 1, count + 1)
            visited[i] = False # 백트래킹의 핵심: 상태 원복

if __name__ == "__main__":
    N = int(sys.stdin.readline())
    S = [list(map(int, sys.stdin.readline().split())) for _ in range(N)]
    visited = [False] * N
    min_diff = float('inf')

    # 0번 멤버를 고정하여 탐색 효율 2배 상승
    visited[0] = True
    dfs(1, 1)
    
    print(min_diff)'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 백트래킹에서 visited 배열을 '넣고 빼는' 타이밍이 실력을 결정합니다. 재귀 호출 직후에 반드시 False로 원복시키는 루틴을 손에 익히세요."}}]
    }}
]

rebuild_one_perfectly("313eacc8-175a-8102-92f6-de849db9395d", "Start & Link", link_full_blocks)
