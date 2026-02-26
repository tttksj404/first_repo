import requests
import json
import time

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def rebuild_perfectly(pid, title, blocks):
    print(f"--- [DEEP REBUILD] {title} ---")
    # 1. Clear
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.05)
    
    # 2. Chunked Patch
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": chunk})
        time.sleep(0.5)
    
    # 3. Verify
    res_verify = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    cnt = len(res_verify.json().get("results", []))
    print(f"VERIFIED: {title} ({cnt} blocks written)")
    return cnt

# --------------------------------------------------------------------------------
# [Problem 14] 상어 초등학교 (Ultra-Detailed)
# --------------------------------------------------------------------------------
school_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 14] 상어 초등학교 - 다중 조건 정렬 및 격자 배치 시뮬레이션"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "문제 요약: 학생들의 자리를 4가지 복합 우선순위 조건에 따라 배치하고, 최종 만족도의 합을 구하는 문제입니다. 정렬 키를 정밀하게 설계하여 최적의 칸을 찾는 능력이 핵심입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석 (Condition)"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "1순위: 비어있는 칸 중 좋아하는 친구가 가장 많이 인접한 칸"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "2순위: 1번 만족 칸이 여러 개면, 인접한 빈 칸이 가장 많은 칸"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "3순위: 2번 만족 칸이 여러 개면 행 번호가 작은 칸, 그다음 열 번호가 작은 칸"}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계 (Logic)"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "현실 로직: 교실의 모든 빈자리를 한 군데씩 다 가보자. 주변에 내 친구가 몇 명인지, 빈자리는 몇 개인지 적어두고 순위에 따라 1등 자리에 앉자."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "코딩 로직: 빈칸 좌표를 순회하며 (좋아하는_친구_수, 인접_빈칸_수, 행, 열) 정보를 수집한다. 파이썬의 sort(key=lambda x: (-x[0], -x[1], x[2], x[3])) 를 쓰면 모든 조건을 한 번에 해결할 수 있다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🏗️ 3. 구현 필수 체크리스트"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "인덱스 체크: 4방향 탐색(dr, dc) 시 0 <= nr < N and 0 <= nc < N 경계를 완벽히 확인했는가?"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "만족도 점수: 0명=0점, 1명=1점, 2명=10점, 3명=100점, 4명=1000점(10^n 형태이나 n=0일 때 주의)을 정확히 구현했는가?"}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 4. Python 전체 정답 코드 (Full Version)"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''import sys

def solve():
    input = sys.stdin.readline
    N = int(input())
    # 학생 순서와 좋아하는 친구 목록 저장
    order = []
    likes = {}
    for _ in range(N*N):
        line = list(map(int, input().split()))
        order.append(line[0])
        likes[line[0]] = set(line[1:])

    grid = [[0]*N for _ in range(N)]
    dr, dc = [-1, 1, 0, 0], [0, 0, -1, 1]

    # 학생 한 명씩 자리 배치 시작
    for student in order:
        candidates = []
        for r in range(N):
            for c in range(N):
                if grid[r][c] == 0:
                    like_cnt, empty_cnt = 0, 0
                    for i in range(4):
                        nr, nc = r + dr[i], c + dc[i]
                        if 0 <= nr < N and 0 <= nc < N:
                            if grid[nr][nc] in likes[student]:
                                like_cnt += 1
                            if grid[nr][nc] == 0:
                                empty_cnt += 1
                    # (-좋아요, -빈칸, r, c) 순서로 수집하여 오름차순 정렬 활용
                    candidates.append((like_cnt, empty_cnt, r, c))
        
        candidates.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
        best_r, best_c = candidates[0][2], candidates[0][3]
        grid[best_r][best_c] = student

    # 최종 점수 계산
    ans = 0
    score_map = {0: 0, 1: 1, 2: 10, 3: 100, 4: 1000}
    for r in range(N):
        for c in range(N):
            cnt = 0
            for i in range(4):
                nr, nc = r + dr[i], c + dc[i]
                if 0 <= nr < N and 0 <= nc < N:
                    if grid[nr][nc] in likes[grid[r][c]]:
                        cnt += 1
            ans += score_map[cnt]
    print(ans)

solve()'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: '모든 칸을 다 뒤져야 하나?'라는 생각이 들 때 주저하지 마세요. N이 작으면(최대 20) 전수조사가 가장 빠르고 정확한 방법입니다. 정렬 키 설계 능력이 합격을 가릅니다."}}]
    }}
]

rebuild_perfectly("313eacc8-175a-812a-bed2-fbacb1f93d1c", "Shark Elementary", school_blocks)
