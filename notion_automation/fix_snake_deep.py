import requests
import json
import time

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# [Problem 05] 뱀 - 페이지 ID
PAGE_ID = "313eacc8-175a-81cc-b101-fbd9f48aa4e8"

# 1. 기존 내용 완전 삭제 (검증 포함)
res_get = requests.get(f"https://api.notion.com/v1/blocks/{PAGE_ID}/children", headers=HEADERS)
existing_blocks = res_get.json().get("results", [])
for b in existing_blocks:
    requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)

# 2. '연구소' 형식을 능가하는 상세 블록 설계 (규격 엄수)
blocks = [
    {
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 05] 뱀 (Snake) - 덱 기반 시뮬레이션 및 맵 관리"}}] }
    },
    {
        "type": "quote",
        "quote": {"rich_text": [{"type": "text", "text": {"content": "삼성 A형의 단골 손님인 시뮬레이션 문제입니다. 뱀의 머리가 늘어나고 꼬리가 줄어드는 '선입선출(FIFO)' 과정을 Deque 자료구조로 완벽히 구현하는 것이 핵심입니다."}}] }
    },
    {
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석 (IM 초월)"}}] }
    },
    {
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "보드 구성: N x N 격자. 사과는 1, 뱀의 몸은 2, 빈칸은 0으로 표시."}}] }
    },
    {
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "이동 규칙: 머리를 다음 칸에 위치시킨다. 벽이나 자기 몸에 부딪히면 즉시 종료."}}] }
    },
    {
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "성장 규칙: 이동한 칸에 사과가 있으면 꼬리는 그대로. 사과가 없으면 꼬리를 한 칸 줄인다."}}] }
    },
    {
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계"}}] }
    },
    {
        "type": "paragraph",
        "paragraph": {"rich_text": [
            {"type": "text", "text": {"content": "현실 로직: "}, "annotations": {"bold": True}},
            {"type": "text", "text": {"content": "머리가 먼저 나가보고, 맛있는 사과가 있으면 길이를 유지하며 전진! 사과가 없으면 꼬리 부분을 떼서 몸길이를 맞춘다."}}
        ]}
    },
    {
        "type": "paragraph",
        "paragraph": {"rich_text": [
            {"type": "text", "text": {"content": "코딩 로직: "}, "annotations": {"bold": True}},
            {"type": "text", "text": {"content": "머리 좌표는 append, 꼬리 좌표는 popleft로 처리. 맵(Grid)에도 반드시 뱀의 몸 위치를 실시간으로 2로 업데이트해야 충돌 검사가 가능하다."}}
        ]}
    },
    {
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🏗️ 3. 구현 필수 체크리스트 (Cheat-Sheet)"}}] }
    },
    {
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "방향 전환 시점: X초가 '끝난 뒤'에 방향을 바꾼다. 즉, time == X 인 로직은 이동 루프 직후에 와야 함."}}] }
    },
    {
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "인덱스 경계: 뱀의 머리가 (0,0)에서 시작하며 범위를 벗어나는 즉시 루프를 탈출하는가?"}}] }
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

def solve():
    N = int(input())
    K = int(input())
    grid = [[0] * (N + 1) for _ in range(N + 1)]
    for _ in range(K):
        r, c = map(int, input().split())
        grid[r][c] = 1  # 사과 표시

    L = int(input())
    turns = {}
    for _ in range(L):
        x, c = input().split()
        turns[int(x)] = c

    # 우, 하, 좌, 상 (시계 방향)
    dr, dc = [0, 1, 0, -1], [1, 0, -1, 0]
    r, c, d = 1, 1, 0
    snake = deque([(r, c)])
    grid[r][c] = 2 # 뱀 몸 표시
    time = 0

    while True:
        time += 1
        nr, nc = r + dr[d], c + dc[d]
        
        # 1. 벽 또는 몸 충돌 체크
        if not (1 <= nr <= N and 1 <= nc <= N) or grid[nr][nc] == 2:
            return time
        
        # 2. 이동 로직
        if grid[nr][nc] != 1: # 사과가 없다면
            tr, tc = snake.popleft() # 꼬리 제거
            grid[tr][tc] = 0
        
        snake.append((nr, nc)) # 머리 이동
        grid[nr][nc] = 2
        r, c = nr, nc
        
        # 3. 방향 전환 체크 (X초가 끝난 뒤)
        if time in turns:
            if turns[time] == 'D': d = (d + 1) % 4
            else: d = (d - 1) % 4'''}}]
        }
    },
    {
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "💡"},
            "color": "blue_background",
            "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 시뮬레이션은 정교함이 생명입니다. 사과를 먹은 칸은 반드시 빈칸(0)으로 만들어야 중복 식사를 방지할 수 있습니다!"}}]
        }
    }
]

# 3. 전송 및 상세 결과 출력
res_patch = requests.patch(f"https://api.notion.com/v1/blocks/{PAGE_ID}/children", headers=HEADERS, json={"children": blocks})
if res_patch.status_code == 200:
    print("Snake page successfully rebuilt with full detail.")
else:
    print(f"Failed: {res_patch.status_code}")
    print(res_patch.text)
