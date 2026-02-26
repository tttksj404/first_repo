# -*- coding: utf-8 -*-
import requests
import json
import sys

TOKEN = "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"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def append_blocks(page_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    requests.patch(url, json={"children": blocks}, headers=HEADERS)

# Adding student-perspective notes that synthesize the above content for better readability
STUDENT_SUMMARY = [
    {"object": "block", "type": "divider", "divider": {}},
    {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "📚 [학생 시점] DFS/BFS 종합 가이드 및 요약"}}]}},
    {"object": "block", "type": "callout", "callout": {
        "rich_text": [{"text": {"content": "위의 정석적인 내용들을 공부하고 난 뒤, 제가 이해하기 쉽게 핵심만 다시 묶어보았습니다."}}],
        "icon": {"emoji": "📖"}
    }},
    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "1. 상황별 알고리즘 매칭 (정리)"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 연결 덩어리 찾기: DFS / BFS 모두 가능 (예: 단지 번호 붙이기)"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 최단 경로 찾기: BFS (예: 미로 탐색, 토마토)"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 모든 가능성 탐색: DFS + 백트래킹 (예: 테트로미노)"}}]}},
    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "2. 실전 꿀팁: 실수하기 쉬운 포인트"}}]}},
    {"object": "block", "type": "quote", "quote": {"rich_text": [{"text": {"content": "- 델타 탐색(dx, dy)과 범위 체크는 항상 세트!\n- 방문 처리(Visited)는 중복 방지를 위해 필수!\n- 백트래킹 시 상태 복구(visited = False)를 잊지 말자!"}}]}},
    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "기존에 적어주신 상세한 코드들과 함께 이 요약본을 보니 훨씬 가독성이 좋아진 것 같아요!"}}]}}
]

if __name__ == "__main__":
    page_id = "2f0eacc8-175a-805c-85b2-dca59899d3d8"
    append_blocks(page_id, STUDENT_SUMMARY)
    print("Successfully appended the summary guide.")
