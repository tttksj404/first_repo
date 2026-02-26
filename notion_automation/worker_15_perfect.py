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
    res_verify = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    cnt = len(res_verify.json().get("results", []))
    print(f"VERIFIED: {title} ({cnt} blocks written)")
    return cnt

# [Problem 15] 원판 돌리기
disk_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 15] 원판 돌리기 - 원형 덱 조작과 인접 제거"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "회전과 인접성 검사가 결합된 시뮬레이션입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 핵심 구현 로직"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "원형 구조: (i+1)%M 식을 사용해 끝점 인접을 처리합니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "인접 제거: 매 회전 후 동일한 수를 찾아 Set에 담아 일괄 삭제합니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 Python 정답 코드"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": "def rotate(disk, d, k): # d=0 CW, d=1 CCW\\n    if d == 0: disk.rotate(k)\\n    else: disk.rotate(-k)"}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 평균값 계산 시 분모가 0이 되는 ZeroDivisionError 예외 처리가 필수입니다."}}]
    }}
]

rebuild_perfectly("313eacc8-175a-8124-a142-c90eadfa6db3", "Disk Rotation", disk_blocks)
