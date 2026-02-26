import requests
import json
import time

NOTION_TOKEN = "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"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def safe_rebuild_full(pid, blocks):
    url = f"https://api.notion.com/v1/blocks/{pid}/children"
    res_get = requests.get(url, headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.1)
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        requests.patch(url, headers=HEADERS, json={"children": chunk})
        time.sleep(0.5)
    return True

# Problem 03 - Full Content
link_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 03] 스타트와 링크 - 백트래킹 기반 팀 매칭 최적화"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "N명을 두 팀으로 나누어 능력치 차이를 최소화하는 조합 최적화 문제입니다. IM 수준의 백트래킹 응용력이 핵심입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "팀 배정: N명 중 N/2명을 뽑는 모든 조합을 탐색합니다. (20C10 = 184,756)"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "시너지 계산: S[i][j] + S[j][i] 공식을 적용하여 각 팀의 점수를 합산합니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "현실 로직: 사람들을 반으로 나눠 모든 대진표를 짜보고 가장 실력 차가 적은 대결을 찾자."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "코딩 로직: DFS(idx, cnt)로 N/2명을 선택. 0번 멤버 고정으로 연산량 50% 단축."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🏗️ 3. 구현 필수 체크리스트"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "재귀 호출 전후로 visited 배열의 상태를 원복(True -> False) 했는가?"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "팀이 나눠진 후 2중 for문으로 모든 멤버 쌍의 시너지를 더했는가?"}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 4. Python 전체 정답 코드"}}]}},
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
        v[i] = True
        dfs(i + 1, cnt + 1)
        v[i] = False

N = int(input())
S = [list(map(int, input().split())) for _ in range(N)]
v = [False]*N; ans = float('inf')
dfs(0, 0); print(ans)'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 백트래킹에서 0번 사람을 한 팀에 고정하는 최적화 기법은 시간 초과를 막는 아주 유용한 기술입니다."}}]
    }}
]

# Problem 04 - Full Content
marble_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 04] 구슬 탈출 2 - 4차원 BFS 및 물리 시뮬레이션"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "빨간 구슬만 탈출시키는 10회 제한 시뮬레이션입니다. '동시 이동'과 '겹침 방지'가 핵심입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🏗️ 핵심 구현 로직"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "4D Visited: visited[rx][ry][bx][by] 배열로 동일 상황 재방문을 방지합니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "중첩 보정: 두 구슬이 겹치면 이동 거리가 더 긴 구슬을 반대 방향으로 한 칸 보정합니다."}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''def move(r, c, dr, dc):
    dist = 0
    while board[r+dr][c+dc] != '#' and board[r][c] != 'O':
        r += dr; c += dc; dist += 1
    return r, c, dist'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 파란 구슬 탈출은 무조건 실패입니다. 동시에 빠지는 케이스를 반드시 체크하세요."}}]
    }}
]

safe_rebuild_full("313eacc8-175a-8102-92f6-de849db9395d", link_blocks)
safe_rebuild_full("313eacc8-175a-8108-9c3a-f2fa6658f3b0", marble_blocks)
