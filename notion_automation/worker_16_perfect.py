import requests
import json
import time

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def rebuild_one(pid, title, blocks):
    print(f"--- [DEEP REBUILD] {title} ---")
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.05)
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": chunk})
        time.sleep(0.5)
    res_verify = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    actual_count = len(res_verify.json().get("results", []))
    print(f"VERIFIED: {title} ({actual_count} blocks)")
    return actual_count

# [Problem 16] 이차원 배열과 연산 (Detailed)
array_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 16] 이차원 배열과 연산 - 빈도 정렬 및 전치 행렬 연산"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "행 또는 열의 길이에 따라 연산 방향을 바꾸며 정렬을 수행하는 문제입니다. 숫자의 등장 빈도를 기준으로 정렬 키를 설계하는 것이 핵심입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 핵심 구현 로직"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "빈도수 정렬: Counter 혹은 딕셔너리로 개수를 세고 (개수, 숫자값) 오름차순으로 정렬합니다. 0은 제외합니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "행/열 변환: 행 연산(R)을 기본으로 짜고, 열 연산(C) 시에는 zip(*)을 이용해 전치시킨 뒤 다시 R 연산을 적용합니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 Python 전체 정답 코드 조각"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''def sort_row(row):
    counts = Counter(row)
    if 0 in counts: del counts[0]
    # 1.빈도 2.숫자 순 정렬
    sorted_res = sorted(counts.items(), key=lambda x: (x[1], x[0]))
    new_row = []
    for num, cnt in sorted_res:
        new_row.extend([num, cnt])
    return new_row[:100] # 최대 100제한'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 연산 후 행/열의 길이를 가장 긴 것에 맞춰 0으로 채우는 Padding 과정에서 인덱스 실수를 주의하세요."}}]
    }}
]

rebuild_one("313eacc8-175a-8172-a54f-fef8428fb6e4", "Array Operation", array_blocks)
print("Updated Problem 16.")
