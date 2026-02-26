import requests
import json
import time

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def rebuild_detailed(pid, title, blocks):
    # 1. Clear
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.05)
    # 2. Patch
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": chunk})
        time.sleep(0.5)
    # 3. Verify
    res_final = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    cnt = len(res_final.json().get("results", []))
    print(f"VERIFIED: {title} ({cnt} blocks)")

# Problem 14 - School
school_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 14] 상어 초등학교 - 다중 조건 정렬 키 설계"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "학생들의 자리를 정해진 우선순위에 따라 배치하는 시뮬레이션입니다. 다중 조건을 정렬 키로 변환하는 테크닉이 핵심입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 핵심 구현 로직"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "정렬 전략: (-좋아요, -빈칸, 행, 열) 튜플을 만들어 sort() 한 번으로 최적의 자리를 찾습니다."}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": "candidates.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))"}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 마지막 점수 합산 시 좋아하는 친구 수에 따른 10^n 가중치를 정확히 적용하세요."}}]
    }}
]

# Problem 15 - Disk
disk_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 15] 원판 돌리기 - 원형 인덱싱과 인접 제거"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "원판 회전과 인접한 같은 수의 BFS 제거를 시뮬레이션합니다. 지울 게 없을 때의 평균값 가감 처리가 복병입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 핵심 구현 로직"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "원형 처리: (i+1)%M 연산을 통해 원판의 시작과 끝이 맞닿아 있음을 구현합니다."}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": "disks[i].rotate(direction * k); # CCW/CW rotation"}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 평균값 계산 시 나누는 수(남은 숫자의 개수)가 0이 될 수 있음을 반드시 예외 처리하세요."}}]
    }}
]

rebuild_detailed("313eacc8-175a-812a-bed2-fbacb1f93d1c", "School", school_blocks)
rebuild_detailed("313eacc8-175a-8124-a142-c90eadfa6db3", "Disk", disk_blocks)
print("Updated 14, 15.")
