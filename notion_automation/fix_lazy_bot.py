import requests
import json
import time

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def safe_patch(pid, blocks):
    """API 끊김 방지(Exponential Backoff)가 적용된 안전한 전송 함수"""
    url = f"https://api.notion.com/v1/blocks/{pid}/children"
    max_retries = 3
    
    # 1. Clear existing safely
    res_get = requests.get(url, headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.1) # Rate Limit 우회
        
    # 2. Patch with Retry
    for attempt in range(max_retries):
        res = requests.patch(url, headers=HEADERS, json={"children": blocks})
        if res.status_code == 200:
            return True
        elif res.status_code in [502, 504, 429]: # 서버 지연 혹은 요청 과다
            print(f"Server busy (Status {res.status_code}). Retrying in {2 ** attempt} seconds...")
            time.sleep(2 ** attempt)
        else:
            print(f"Error: {res.text}")
            return False
    return False

# ---------------------------------------------------------
# [Problem 18] 새로운 게임 2 (초격차 상세 버전)
# ---------------------------------------------------------
game2_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 18] 새로운 게임 2 - 스택 구조와 2차원 리스트 슬라이싱 조작"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "체스판 위에서 말들이 쌓이고, 색상(흰, 빨, 파)에 따라 함께 이동하는 과정을 시뮬레이션합니다. '업혀서 같이 이동'하는 로직 구현이 승부처입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석 (Situation)"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "말의 적층 구조: 한 칸에 여러 말이 쌓일 수 있으므로 grid[r][c] = [] 형태의 2차원 리스트가 필수적입니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "색상별 이동 규칙: 흰색은 순서 유지, 빨간색은 순서 뒤집기, 파란색/경계는 방향 반전 후 1칸 이동(또 파란색이면 정지)."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계 (Logic)"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
        {"type": "text", "text": {"content": "현실의 생각: "}, "annotations": {"bold": True}},
        {"type": "text", "text": {"content": "내 차례가 오면 내 위에 업힌 애들을 몽땅 데리고 이동한다. 빨간색 땅이면 도착해서 순서를 뒤집어 놓는다."}}
    ]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
        {"type": "text", "text": {"content": "코딩 변환: "}, "annotations": {"bold": True}},
        {"type": "text", "text": {"content": "말의 번호를 기준으로 현재 위치(r, c)와 몇 번째 층(idx)에 있는지 찾는다. moving = grid[r][c][idx:] 로 묶음을 분리하고, 원본은 grid[r][c][:idx] 로 갱신한다."}}
    ]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🏗️ 3. 구현 필수 체크리스트 (IM 스타일)"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "파란색/경계 방향 전환: 방향을 바꾸고 한 칸 이동하려 할 때, 거기도 파란색이거나 벽이면 '이동하지 않는다'는 조건을 완벽히 구현했는가?"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "4개 이상 종료 조건: 말이 이동할 때마다 해당 칸의 길이가 4 이상이 되는지 매 턴마다 체크하는가? (1000턴이 넘으면 -1 출력)"}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 4. Python 초정밀 실전 코드"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''# 색상에 따른 이동 로직의 핵심 축약본
def move_piece(piece_num):
    r, c, d = piece_info[piece_num]
    # 현재 말이 몇 번째 층에 있는지 찾기
    for i, num in enumerate(grid[r][c]):
        if num == piece_num:
            idx = i
            break
            
    # 내 위로 엎힌 말들 모두 가져오기
    moving = grid[r][c][idx:]
    grid[r][c] = grid[r][c][:idx] # 남은 말들 갱신
    
    nr, nc = r + dr[d], c + dc[d]
    
    # 1. 파란색이거나 벽인 경우
    if not (0<=nr<N and 0<=nc<N) or board[nr][nc] == 2:
        d = opposite_dir[d] # 방향 반전
        piece_info[piece_num][2] = d
        nr, nc = r + dr[d], c + dc[d]
        # 또 벽이거나 파란색이면 제자리 유지
        if not (0<=nr<N and 0<=nc<N) or board[nr][nc] == 2:
            grid[r][c].extend(moving) # 제자리 복구
            return
            
    # 2. 빨간색인 경우 순서 뒤집기
    if board[nr][nc] == 1:
        moving.reverse()
        
    # 3. 맵에 말 올리기 (흰색은 그냥 그대로)
    grid[nr][nc].extend(moving)
    
    # 말들의 위치 정보(r, c) 일괄 갱신
    for m_num in moving:
        piece_info[m_num][0], piece_info[m_num][1] = nr, nc'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "🎓"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 파이썬의 리스트 슬라이싱 [idx:]와 뒤집기 reverse()를 적극 활용하세요. 이 두 가지를 쓰지 않으면 코드가 수십 줄 길어지고 버그 지옥에 빠집니다."}}]
    }}
]

# ---------------------------------------------------------
# [Problem 20] 스타트 택시 (초격차 상세 버전)
# ---------------------------------------------------------
taxi_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 20] 스타트 택시 - 복합 BFS와 최적화된 연료 관리 시뮬레이션"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "손님을 찾아 모시고 목적지까지 이동하며 연료를 관리하는 시뮬레이션입니다. 매번 최단 거리의 손님을 찾는 '탐색'과 목적지까지의 '운송'이 분리된 복합 BFS입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석 (Situation)"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "손님 선정 우선순위: 1순위 최단 거리, 2순위 가장 행(r)이 작은 곳, 3순위 가장 열(c)이 작은 곳."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "연료 규칙: 이동 시 연료 1 소모, 목적지 도착 시 소모한 연료의 2배 충전. 이동 도중 0이 되면 실패, 도착 순간 0이 되는 것은 성공."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계 (Logic)"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
        {"type": "text", "text": {"content": "현실의 생각: "}, "annotations": {"bold": True}},
        {"type": "text", "text": {"content": "택시는 기름을 아끼기 위해 제일 가까운(거리->위->왼쪽) 손님부터 픽업한다. 벽에 막혀 갈 수 없는 손님은 과감히 버려야 한다."}}
    ]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [
        {"type": "text", "text": {"content": "코딩 변환: "}, "annotations": {"bold": True}},
        {"type": "text", "text": {"content": "택시 위치에서 맵 전체를 돌며 BFS로 모든 좌표까지의 거리 맵(dist_map)을 반환하는 공용 함수를 만든다. 이 거리를 바탕으로 손님 리스트를 정렬하여 0번 손님을 태운다."}}
    ]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🏗️ 3. 구현 필수 체크리스트 (IM 스타일)"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "거리 0의 손님: 택시가 현재 있는 칸에 손님이 서 있는 경우 거리가 0입니다. 이 예외 처리를 누락하면 무한루프에 빠질 수 있습니다."}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "벽으로 막힌 고립 구역: BFS를 돌렸지만 도달 불가능한 경우(초기화값 -1 그대로)를 확실히 거르고 실패 처리했는가?"}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 4. Python 초정밀 실전 코드"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''from collections import deque

def get_dist_map(sr, sc):
    # 단일 시작점에서 맵 전체의 거리를 반환하는 공용 BFS 함수
    dist_map = [[-1]*N for _ in range(N)]
    q = deque([(sr, sc)])
    dist_map[sr][sc] = 0
    
    while q:
        r, c = q.popleft()
        for i in range(4):
            nr, nc = r+dr[i], c+dc[i]
            if 0<=nr<N and 0<=nc<N and grid[nr][nc] != 1 and dist_map[nr][nc] == -1:
                dist_map[nr][nc] = dist_map[r][c] + 1
                q.append((nr, nc))
    return dist_map

# 메인 로직 내 손님 탐색 과정
dist_map = get_dist_map(taxi_r, taxi_c)
candidates = []
for p_id, (pr, pc, dr, dc) in passengers.items():
    if dist_map[pr][pc] != -1: # 도달 가능한 손님만
        candidates.append((dist_map[pr][pc], pr, pc, p_id))

if not candidates: 
    return -1 # 남은 손님이 있는데 도달 불가능

# 1.거리, 2.행, 3.열 순으로 정렬 후 최적의 손님 선택
candidates.sort(key=lambda x: (x[0], x[1], x[2]))
dist_to_p, pr, pc, p_id = candidates[0]'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "🎓"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 거리를 구하는 get_dist_map() 함수를 하나만 제대로 짜두면 '손님 찾기'와 '목적지 가기' 두 곳에 모두 재사용할 수 있습니다! 모듈화가 생명입니다."}}]
    }}
]

print("Executing Game2 Update with Anti-Timeout Logic...")
safe_patch("313eacc8-175a-81a1-b46f-d1de909db499", game2_blocks)
print("Executing Taxi Update with Anti-Timeout Logic...")
safe_patch("313eacc8-175a-81f8-b518-fbfea3edcac5", taxi_blocks)
print("Done.")
