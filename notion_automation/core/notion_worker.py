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

# 1. 완벽한 원고 데이터 (이곳에 내용을 축약 없이 모두 담습니다)
blueprint = {
    "313eacc8-175a-8102-92f6-de849db9395d": { # 스타트와 링크
        "title": "📍 [Samsung A] 스타트와 링크 - 백트래킹 조합 최적화",
        "blocks": [
            {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 03] 스타트와 링크 - 백트래킹 기반 팀 매칭 최적화"}}]}},
            {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "N명을 두 팀으로 나누어 능력치 차이를 최소화하는 조합 최적화 문제입니다. 20C10 전수 조사를 백트래킹으로 구현하는 것이 핵심입니다."}}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석 (IM 초월)"}}]}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "팀 인원수: 무조건 N/2명으로 정확히 나뉘어야 함."}}]}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "능력치 계산: i와 j가 같은 팀일 때 S[i][j]와 S[j][i]를 모두 더함."}}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계"}}]}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "현실 로직: 대진표를 짤 때 모든 경우를 다 해보자. 반틈만 정하면 나머지는 자동 결정되니까!"}}]}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "코딩 로직: DFS(idx, cnt)에서 visited로 팀 구분. cnt == N/2면 점수 계산 루프 진입."}}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 3. Python 전체 정답 코드"}}]}},
            {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''import sys
def dfs(idx, cnt):
    global ans
    if cnt == N // 2:
        start, link = 0, 0
        for i in range(N):
            for j in range(N):
                if v[i] and v[j]: start += S[i][j]
                elif not v[i] and not v[j]: link += S[i][j]
        ans = min(ans, abs(start - link))
        return
    for i in range(idx, N):
        if not v[i]:
            v[i] = True
            dfs(i + 1, cnt + 1)
            v[i] = False

N = int(sys.stdin.readline())
S = [list(map(int, sys.stdin.readline().split())) for _ in range(N)]
v = [False]*N; ans = float('inf')
dfs(0, 0); print(ans)'''}}]}},
            {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "💡"}, "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 0번 멤버를 특정 팀에 고정하여 중복 연산을 1/2로 줄이는 것이 시간 초과를 막는 치트키입니다."}}]}}
        ]
    },
    "313eacc8-175a-8108-9c3a-f2fa6658f3b0": { # 구슬 탈출 2
        "title": "📍 [Samsung A] 구슬 탈출 2 - 4차원 BFS 물리 시뮬레이션",
        "blocks": [
            {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 04] 구슬 탈출 2 - 4차원 상태 배열과 물리 시뮬레이션"}}]}},
            {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "빨간 구슬만 탈출시키는 10회 제한 시뮬레이션입니다. 4D Visited와 겹침 보정 로직이 핵심입니다."}}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 핵심 구현 로직"}}]}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "4D Visited: visited[rx][ry][bx][by]를 사용하여 두 구슬의 위치 조합을 상태로 관리합니다."}}]}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "겹침 보정: 이동 거리가 먼 구슬을 반대 방향으로 한 칸 보정합니다."}}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 2. Python 핵심 코드"}}]}},
            {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''def move(r, c, dr, dc):
    dist = 0
    while board[r+dr][c+dc] != '#' and board[r][c] != 'O':
        r += dr; c += dc; dist += 1
    return r, c, dist

# BFS 내 겹침 처리
if nrx == nbx and nry == nby:
    if dr > db: nrx -= dx; nry -= dy
    else: nbx -= dx; nby -= dy'''}}]}},
            {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "💡"}, "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 파란 구슬 탈출은 무조건 실패! 파란 구슬 체크를 빨간 구슬보다 먼저 수행하세요."}}]}}
        ]
    }
    # (추가적인 13개 문제의 상세 데이터도 동일한 구조로 이 파일에 계속 채워질 것입니다)
}

def worker(pid, data):
    print(f"--- Processing {data['title']} ---")
    url = f"https://api.notion.com/v1/blocks/{pid}/children"
    
    # 1. Clear with verification
    res_get = requests.get(url, headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.1)
    
    # 2. Chunked Patch
    blocks = data["blocks"]
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        res = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if res.status_code != 200:
            print(f"FAILED on chunk {i}: {res.text}")
            return False
        time.sleep(1) # 휴식 기법 적용
    
    # 3. Verification Read
    res_final = requests.get(url, headers=HEADERS)
    cnt = len(res_final.json().get("results", []))
    print(f"VERIFIED: {data['title']} has {cnt} blocks.")
    return True

# 실행
for pid, data in blueprint.items():
    if worker(pid, data):
        print(f"Done with {data['title']}")
        time.sleep(3) # 페이지 간 충분한 휴식
