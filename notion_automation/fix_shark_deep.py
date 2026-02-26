import requests
import json
import time

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# 2. [Samsung A] 아기 상어 - 초격차 심화 버전 재구축
PAGE_ID = "313eacc8-175a-81e5-a57e-d33266fd300c"

# Clear existing
res_get = requests.get(f"https://api.notion.com/v1/blocks/{PAGE_ID}/children", headers=HEADERS)
for b in res_get.json().get("results", []):
    requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)

blocks = [
    {
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 02] 아기 상어 (Baby Shark) - 우선순위 BFS 탐색"}}] }
    },
    {
        "type": "quote",
        "quote": {"rich_text": [{"type": "text", "text": {"content": "문제 요약: $N 	imes N$ 공간에서 아기 상어가 성장하며 물고기를 잡아먹는 시간을 구합니다. '최단 거리', '상단 우선', '좌측 우선'이라는 3단 조건을 BFS 탐색 결과에 정확히 녹여내는 것이 승부처입니다."}}] }
    },
    {
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석"}}] }
    },
    {
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "크기 규칙: 초기 2. 먹은 개수가 현재 크기와 같아지면 크기 +1. 자신보다 큰 물고기는 벽으로 간주."}}] }
    },
    {
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "종료 조건: 맵에 더 이상 먹을 수 있는 물고기가 없으면 시뮬레이션 종료."}}] }
    },
    {
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계"}}] }
    },
    {
        "type": "paragraph",
        "paragraph": {"rich_text": [
            {"type": "text", "text": {"content": "현실 로직: "}, "annotations": {"bold": True}},
            {"type": "text", "text": {"content": "배가 고프다! 주변을 훑어서 가장 가까운 사냥감을 찾자. 만약 거리가 같다면 북서쪽(위쪽, 왼쪽)에 있는 놈부터 먹으러 전진한다."}}
        ]}
    },
    {
        "type": "paragraph",
        "paragraph": {"rich_text": [
            {"type": "text", "text": {"content": "코딩 로직: "}, "annotations": {"bold": True}},
            {"type": "text", "text": {"content": "매 사냥 턴마다 BFS를 돌린다. 큐에서 꺼낼 때 '상어 크기보다 작은 물고기'를 발견하면 후보 리스트에 (거리, r, c)를 담는다. BFS가 완전히 끝난 후 리스트를 정렬하여 최적의 대상을 먹는다."}}
        ]}
    },
    {
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🏗️ 3. 구현 필수 체크리스트"}}] }
    },
    {
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "BFS 탐색 중 물고기를 발견하자마자 리턴하지 않았는가? (전수 조사 후 정렬 필수)"}}] }
    },
    {
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "물고기를 먹은 칸을 0(빈칸)으로 갱신했는가?"}}] }
    },
    {
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 4. Python 실전 정답 코드"}}] }
    },
    {
        "type": "code",
        "code": {
            "language": "python",
            "rich_text": [{"type": "text", "text": {"content": '''from collections import deque

def find_fish(shark_r, shark_c, size):
    q = deque([(shark_r, shark_c, 0)])
    visited = [[False]*N for _ in range(N)]
    visited[shark_r][shark_c] = True
    cands = []
    
    while q:
        r, c, dist = q.popleft()
        for i in range(4):
            nr, nc = r+dr[i], c+dc[i]
            if 0<=nr<N and 0<=nc<N and not visited[nr][nc]:
                if grid[nr][nc] <= size: # 통과 가능
                    visited[nr][nc] = True
                    if 0 < grid[nr][nc] < size: # 사냥 가능
                        cands.append((dist+1, nr, nc))
                    else:
                        q.append((nr, nc, dist+1))
    return sorted(cands) # (거리, r, c) 순으로 자동 정렬'''}}]
        }
    },
    {
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "💡"},
            "color": "blue_background",
            "rich_text": [{"type": "text", "text": {"content": "학생 가이드: '최단 거리 내 우선순위' 조건이 붙으면 BFS 탐색이 끝난 뒤 수집된 데이터를 직접 정렬하는 것이 가장 안전하고 빠른 방법입니다."}}]
        }
    }
]

res_patch = requests.patch(f"https://api.notion.com/v1/blocks/{PAGE_ID}/children", headers=HEADERS, json={"children": blocks})
if res_patch.status_code == 200:
    print("Shark page rebuilt with full detail.")
else:
    print(res_patch.text)
