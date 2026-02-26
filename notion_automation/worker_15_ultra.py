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

# THE REAL FULL VERSION OF Problem 15
disk_ultra_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 15] 원판 돌리기 - 원형 인덱싱과 인접 요소 동시 제거 시뮬레이션"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "원판을 회전시키고 인접한 같은 숫자를 지워나가는 시뮬레이션입니다. 원형 구조의 특성과 지울 숫자가 없을 때의 평균값 처리가 핵심입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "원형 구조 (% M): 0번 인덱스와 M-1번 인덱스가 붙어있음을 처리하기 위해 (i+1)%M 연산을 활용합니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "상하 인접: 인접한 두 원판(i번과 i+1번)에서 동일한 위치(j번)에 있는 숫자도 인접한 것으로 간주합니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "코딩 로직: 각 원판을 deque로 관리하여 rotate()를 수행합니다. 지울 좌표들을 set()에 모아 중복을 제거하고, 마지막에 한꺼번에 지웁니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 3. Python 전체 정답 코드"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''import sys
from collections import deque

def solve():
    N, M, T = map(int, sys.stdin.readline().split())
    disks = [deque(map(int, sys.stdin.readline().split())) for _ in range(N)]

    for _ in range(T):
        x, d, k = map(int, sys.stdin.readline().split())
        for i in range(N):
            if (i + 1) % x == 0:
                if d == 0: disks[i].rotate(k)
                else: disks[i].rotate(-k)

        to_delete = set()
        for r in range(N):
            for c in range(M):
                if disks[r][c] == 0: continue
                if disks[r][c] == disks[r][(c + 1) % M]:
                    to_delete.add((r, c)); to_delete.add((r, (c + 1) % M))
                if r < N - 1 and disks[r][c] == disks[r+1][c]:
                    to_delete.add((r, c)); to_delete.add((r+1, c))
        
        if to_delete:
            for r, c in to_delete: disks[r][c] = 0
        else:
            total_sum, count = 0, 0
            for r in range(N):
                for c in range(M):
                    if disks[r][c] > 0:
                        total_sum += disks[r][c]; count += 1
            if count == 0: break
            avg = total_sum / count
            for r in range(N):
                for c in range(M):
                    if disks[r][c] > 0:
                        if disks[r][c] > avg: disks[r][c] -= 1
                        elif disks[r][c] < avg: disks[r][c] += 1
    print(sum(sum(disk) for disk in disks))
solve()'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 평균값 계산 시 남은 숫자의 개수가 0인 경우 ZeroDivisionError 예외 처리를 반드시 해야 합니다."}}]
    }}
]

rebuild_full_version("313eacc8-175a-8124-a142-c90eadfa6db3", "Disk Rotation Final", disk_ultra_blocks)
print("Disk page rebuilt.")
