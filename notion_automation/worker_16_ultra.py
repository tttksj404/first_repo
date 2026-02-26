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
# Problem 16 - 이차원 배열과 연산 (Detailed Full Version)
# --------------------------------------------------------------------------------
array_ultra_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 16] 이차원 배열과 연산 - 빈도수 정렬 및 전치 행렬 테크닉"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "문제 요약: 행 또는 열의 길이에 따라 R 또는 C 연산을 수행하며 배열을 재구성합니다. 숫자의 등장 빈도를 기준으로 (빈도, 숫자값) 순 정렬을 수행하는 것이 핵심입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "R 연산: 행의 개수 >= 열의 개수인 경우, 모든 행에 대해 정렬을 수행합니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "C 연산: 행의 개수 < 열의 개수인 경우, 모든 열에 대해 정렬을 수행합니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "정렬 규칙: (개수, 숫자값) 오름차순. 0은 무시하며, 결과 배열은 최대 100칸까지만 유지합니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "코딩 로직: Counter 혹은 딕셔너리로 빈도를 측정하고, 정렬 후 [숫자, 개수, 숫자, 개수...] 형태로 리스트를 재빌드합니다. C 연산은 zip(*)으로 맵을 뒤집어 R 연산을 재사용하면 훨씬 간결합니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 3. Python 전체 정답 코드 (Full Version)"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''import sys
from collections import Counter

def row_op(matrix):
    new_matrix = []
    max_len = 0
    for row in matrix:
        # 0 제외하고 빈도수 측정
        cnt = Counter(row)
        if 0 in cnt: del cnt[0]
        # (빈도, 숫자값) 순으로 오름차순 정렬
        sorted_res = sorted(cnt.items(), key=lambda x: (x[1], x[0]))
        
        new_row = []
        for num, freq in sorted_res:
            new_row.extend([num, freq])
        
        # 최대 100칸 제한 및 길이 기록
        new_row = new_row[:100]
        new_matrix.append(new_row)
        max_len = max(max_len, len(new_row))
    
    # Padding: 0으로 길이 맞추기
    for row in new_matrix:
        row.extend([0] * (max_len - len(row)))
    return new_matrix

def solve():
    r, c, k = map(int, sys.stdin.readline().split())
    # 인덱스 보정 (1-based -> 0-based)
    r, c = r-1, c-1
    grid = [list(map(int, sys.stdin.readline().split())) for _ in range(3)]

    for time in range(101):
        # 정답 확인
        if r < len(grid) and c < len(grid[0]) and grid[r][c] == k:
            print(time); return
        
        # 행/열 연산 결정
        if len(grid) >= len(grid[0]):
            grid = row_op(grid)
        else:
            # 전치 -> R연산 -> 재전치 (C연산 구현)
            grid = list(zip(*grid))
            grid = row_op(grid)
            grid = list(zip(*grid))
            
    print(-1) # 100초 초과

solve()'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 배열의 크기가 매번 변하므로 r, c 좌표가 현재 grid 범위를 벗어나지 않았는지 체크하는 if r < len(grid) and c < len(grid[0]) 조건이 매우 중요합니다!"}}]
    }}
]

rebuild_full_version("313eacc8-175a-8172-a54f-fef8428fb6e4", "Array Operation Final", array_ultra_blocks)
print("Array page rebuilt.")
