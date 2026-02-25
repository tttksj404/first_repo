# -*- coding: utf-8 -*-
import requests
import json
import sys

TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def append_blocks(page_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    requests.patch(url, json={"children": blocks}, headers=HEADERS)

# Adding student-perspective notes at the end of the existing content
STUDENT_NOTES = [
    {"object": "block", "type": "divider", "divider": {}},
    {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "👨‍💻 학생의 추가 학습: Greedy 더 깊게 파보기"}}]}},
    {"object": "block", "type": "callout", "callout": {
        "rich_text": [{"text": {"content": "사용자님이 정리해주신 기본 개념을 바탕으로, 실전 문제를 풀며 제가 더 알게 된 내용들을 정리해봤습니다!"}}],
        "icon": {"emoji": "📖"}
    }},
    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "1. 단순 그리디 vs 파라메트릭 서치 (Parametric Search)"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "2805번(나무 자르기): '적어도 M만큼'이라는 조건이 나오면 이분 탐색(Parametric Search)을 의심해보자!"}}]}},
    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "2. 시간 초과를 피하는 그리디의 지혜"}}]}},
    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "10162번(전자레인지) 문제를 통해 큰 단위부터 나누고 나머지 연산(%)을 쓰는 효율성을 배웠습니다."}}]}},
    {"object": "block", "type": "code", "code": {
        "language": "python",
        "rich_text": [{"text": {"content": "# Greedy Logic Example\nitems.sort(key=lambda x: x[1], reverse=True)\nfor item in items:\n    if capacity >= item[0]:\n        capacity -= item[0]\n        total_value += item[1]"}}]
    }}
]

if __name__ == "__main__":
    page_id = "2feeacc8-175a-80ee-9739-cb395ef4cc64"
    append_blocks(page_id, STUDENT_NOTES)
    print("Appended new insights successfully.")
