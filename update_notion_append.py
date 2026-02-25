# -*- coding: utf-8 -*-
import requests
import json
import sys

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def append_blocks(page_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    payload = {"children": blocks}
    res = requests.patch(url, json=payload, headers=HEADERS)
    if res.status_code != 200:
        print(f"Error appending blocks: {res.text}")

# 학생 시점의 보강용 컨텐츠 (한글 포함)
# 이 블록들은 '기존 내용' 뒤에 붙게 됩니다.
STUDENT_NOTES = [
    {"object": "block", "type": "divider", "divider": {}},
    {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🎓 학생의 시선: DFS/BFS를 공부하며 느낀 핵심 정리"}}]}},
    {"object": "block", "type": "callout", "callout": {
        "rich_text": [{"text": {"content": "처음에는 DFS와 BFS가 비슷해 보였는데, '최단 거리'를 물어보면 BFS를, '모든 경로 탐색'이나 '깊이'가 중요하다면 DFS를 쓰는 게 국룰이라는 걸 깨달았습니다!"}}],
        "icon": {"emoji": "💡"}
    }},
    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "⚠️ 내가 실수했던 부분 (Mistake Notes)"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "DFS 재귀 호출 시 방문 처리를 '들어가기 전'에 할지, '들어온 후'에 할지 헷갈렸는데, 일관성 있게 '큐/스택에 넣기 직전'에 하는 게 중복 방문을 막는 데 가장 안전하더라고요."}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "BFS에서 collections.deque를 안 쓰고 일반 list.pop(0)을 썼다가 시간 초과(O(N))로 고생한 적이 있습니다. 무조건 popleft()를 씁시다!"}}]}},
    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "🚀 실전 응용: 멀티소스 BFS (7576 토마토 등)"}}]}},
    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "시작점이 여러 개인 경우, 각각 BFS를 돌리는 게 아니라 '모든 시작점을 한꺼번에 큐에 넣고' 시작하는 게 포인트입니다. 그래야 각 지점까지의 최단 거리가 동시에 퍼져나가며 정답이 나옵니다."}}]}},
    {"object": "block", "type": "code", "code": {
        "language": "python",
        "rich_text": [{"text": {"content": "# Multi-source BFS logic: Enqueue all start nodes first\nqueue = deque()\nfor r in range(N):\n    for c in range(M):\n        if grid[r][c] == 1: # Starting points\n            queue.append((r, c))\n            visited[r][c] = 0"}}]
    }},
    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "📌 코드 작성 템플릿 (기억용)"}}]}},
    {"object": "block", "type": "quote", "quote": {"rich_text": [{"text": {"content": "1. 문제 읽고 DFS vs BFS 결정\n2. 상하좌우(dr, dc) 설정\n3. 방문 처리 배열(visited) 생성\n4. 범위 체크(is_valid) + 방문 여부 확인\n5. 결과값 도출 (최대값, 최소값, 개수 등)"}}]}}
]

if __name__ == "__main__":
    page_id = "2f0eacc8-175a-805c-85b2-dca59899d3d8"
    print("Appending rich algorithm notes to page...")
    append_blocks(page_id, STUDENT_NOTES)
    print("Update complete!")
