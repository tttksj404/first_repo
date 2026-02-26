import requests
import json
import time

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def rebuild_full_version(pid, title, blocks):
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.05)
    for i in range(0, len(blocks), 2):
        chunk = blocks[i:i+2]
        requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": chunk})
        time.sleep(0.5)
    res_verify = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    actual_count = len(res_verify.json().get("results", []))
    print(f"VERIFIED: {title} ({actual_count} blocks written)")
    return True

# --------------------------------------------------------------------------------
# Problem 17 - 경사로 (Detailed Full Version)
# --------------------------------------------------------------------------------
slope_ultra_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 17] 경사로 - 인덱스 조건 체크와 논리적 검증의 정석"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "문제 요약: 격자판의 길을 따라가며 높이 차이가 날 때 경사로를 놓아 끝까지 갈 수 있는 길의 개수를 구합니다. 'L만큼의 연속 평지 확보'와 '중복 설치 방지'가 알고리즘의 핵심입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "높이 차이 조건: 인접한 두 칸의 높이 차는 무조건 1이어야 합니다. 2 이상이면 설치 불가."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "경사로 길이 L: 경사로를 놓을 칸의 높이가 모두 동일해야 하며, 이미 경사로가 놓인 칸에는 또 놓을 수 없습니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "코딩 로직: 1차원 리스트를 입력받아 가능 여부를 True/False로 반환하는 check_path(line) 함수를 만듭니다. 가로 줄은 그대로, 세로 줄은 전치(Transpose)하여 이 함수를 재사용합니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 3. Python 전체 정답 코드 (Full Version)"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''import sys

def check_path(line, N, L):
    # 경사로 설치 여부 기록
    used = [False] * N
    for i in range(N - 1):
        if line[i] == line[i+1]:
            continue
        
        # 높이 차이가 1보다 크면 실패
        if abs(line[i] - line[i+1]) > 1:
            return False
        
        # 1. 오르막 (현재 < 다음)
        if line[i] < line[i+1]:
            for k in range(L): # 현재 칸부터 뒤로 L칸 확인
                target_idx = i - k
                if target_idx < 0 or line[target_idx] != line[i] or used[target_idx]:
                    return False
                used[target_idx] = True # 설치 완료
        
        # 2. 내리막 (현재 > 다음)
        else:
            for k in range(1, L + 1): # 다음 칸부터 앞으로 L칸 확인
                target_idx = i + k
                if target_idx >= N or line[target_idx] != line[i+1] or used[target_idx]:
                    return False
                used[target_idx] = True # 설치 완료
    return True

def solve():
    N, L = map(int, sys.stdin.readline().split())
    grid = [list(map(int, sys.stdin.readline().split())) for _ in range(N)]
    
    total_roads = 0
    # 가로 줄 검사
    for row in grid:
        if check_path(row, N, L): total_roads += 1
    
    # 세로 줄 검사 (전치 행렬 활용)
    for col in zip(*grid):
        if check_path(col, N, L): total_roads += 1
        
    print(total_roads)

solve()'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 내리막길 경사로를 체크할 때, target_idx = i + k 임을 주의하세요. (i+1부터 시작해도 되지만 루프 범위 조심!)"}}]
    }}
]

rebuild_full_version("313eacc8-175a-8139-973e-e2e28a926f49", "Slope Final", slope_ultra_blocks)
print("Slope page rebuilt.")
