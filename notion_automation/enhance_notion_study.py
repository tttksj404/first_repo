import requests
import json

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PARENT_PAGE_ID = "2e7eacc8-175a-8035-8d30-ca6bf5e1c524"

def get_children(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    res = requests.get(url, headers=HEADERS)
    return res.json().get("results", [])

# Define deep insights for each concept
deep_guides = {
    "DFS/BFS": {
        "template": '''# 2D 델타 탐색 표준 양식
dx, dy = [-1, 1, 0, 0], [0, 0, -1, 1]
q = deque([(start_r, start_c)])
visited[start_r][start_c] = 1 # or 0
while q:
    r, c = q.popleft()
    for i in range(4):
        nr, nc = r + dx[i], c + dy[i]
        if 0 <= nr < N and 0 <= nc < M and not visited[nr][nc]:
            # 로직 수행''',
        "hybrid": ["BFS + 시뮬레이션: 맵이 매 초마다 변할 때 (예: 토마토, 인구 이동). 반드시 '현재 큐 크기만큼만' 돌리는 q_size 패턴 사용.", "DFS + 백트래킹: 모든 조합을 따져야 할 때. visited 해제 로직 필수."]
    },
    "투포인터,그리디": {
        "template": '''# 그리디/투포인터 기본 (정렬 필수인 경우가 많음)
arr.sort()
l, r = 0, len(arr) - 1
while l < r:
    current = arr[l] + arr[r]
    if current == target: break
    elif current < target: l += 1
    else: r -= 1''',
        "hybrid": ["그리디 + 우선순위 큐: 매 순간 가장 가치가 높은/낮은 것을 골라야 할 때 (예: 회의실 배정, 보석 도둑).", "투포인터 + 슬라이딩 윈도우: 고정된 크기 혹은 가변 크기의 구간합을 구할 때."]
    },
    "이진 탐색": {
        "template": '''# 파라메트릭 서치 표준 양식
low, high = min_val, max_size
ans = 0
while low <= high:
    mid = (low + high) // 2
    if check(mid): # 조건 만족 여부 결정 함수
        ans = mid # 일단 답으로 기록
        low = mid + 1 # 더 큰 값 탐색
    else:
        high = mid - 1''',
        "hybrid": ["이진 탐색 + 그리디: '최솟값의 최댓값'을 구하라는 문제에서 check() 함수를 그리디하게 설계하는 방식."]
    },
    "DP": {
        "template": '''# DP 테이블 초기화 및 점화식
dp = [0] * (N + 1)
dp[1], dp[2] = base1, base2
for i in range(3, N + 1):
    dp[i] = max(dp[i-1], dp[i-2] + val)''',
        "hybrid": ["DP + DFS: 메모이제이션(Memoization). 복잡한 상태 전이가 있을 때 재귀로 풀되 결과를 저장.", "DP + 비트마스크: 선택 여부를 비트로 표현해야 할 때 (TSP 문제 등)."]
    }
}

subpages = [b for b in get_children(PARENT_PAGE_ID) if b["type"] == "child_page"]

for sp in subpages:
    page_id = sp["id"]
    title = sp["child_page"]["title"]
    
    for key in deep_guides:
        if key in title:
            blocks = [
                {"object": "block", "type": "divider", "divider": {}},
                {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": f"🏗️ [{key}] 필수 구현 양식 (Standard Template)"}}]}},
                {"object": "block", "type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": deep_guides[key]["template"]}}]}},
                {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🧩 응용/혼합 패턴 & 설계 주의점"}}]}}
            ]
            for h in deep_guides[key]["hybrid"]:
                blocks.append({
                    "object": "block", 
                    "type": "bulleted_list_item", 
                    "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": h, "annotations": {"bold": True}}}]}
                })
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            
            requests.patch(f"https://api.notion.com/v1/blocks/{page_id}/children", headers=HEADERS, json={"children": blocks})
            print(f"Deep update complete for: {title}")
            break

print("All major algorithm study pages have been enhanced with templates and hybrid patterns.")
