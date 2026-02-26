import requests
import json

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PARENT_PAGE_ID = "2e7eacc8-175a-8035-8d30-ca6bf5e1c524"

def get_children(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    res = requests.get(url, headers=HEADERS)
    return res.json().get("results", [])

def append_checklist(page_id, title, items, mistakes):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    blocks = [
        {"object": "block", "type": "divider", "divider": {}},
        {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": f"⚠️ [실수 방지] {title} 오답 노트 & 최종 체크리스트"}}]}},
        {"object": "block", "type": "callout", "callout": {
            "icon": {"type": "emoji", "emoji": "🚫"},
            "color": "red_background",
            "rich_text": [{"type": "text", "text": {"content": f"과거의 실수 포인트: {mistakes}"}}]
        }}
    ]
    for item in items:
        blocks.append({
            "object": "block", 
            "type": "bulleted_list_item", 
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": item}}]}
        })
    blocks.append({"object": "block", "type": "divider", "divider": {}})
    
    res = requests.patch(url, headers=HEADERS, json={"children": blocks})
    return res.status_code

# 1. Get all subpages
subpages = [b for b in get_children(PARENT_PAGE_ID) if b["type"] == "child_page"]

# 2. Define templates for each category (based on common patterns in the study)
checklists = {
    "해시": {
        "mistakes": "Key 존재 여부 확인 누락, 중복 데이터 처리 미흡.",
        "items": ["dict.get(key, default)를 활용해 KeyError를 방지했는가?", "Value 업데이트 시 기존 값을 고려했는가?"]
    },
    "배열 & 문자열": {
        "mistakes": "인덱스 범위(N-1) 착각, 슬라이싱 시 끝점 미포함 실수.",
        "items": ["range(start, end)에서 end는 포함되지 않음을 인지했는가?", "빈 문자열이나 1개짜리 배열 등 극단적 케이스를 확인했는가?"]
    },
    "투포인터,그리디": {
        "mistakes": "그리디 정당성 증명 부족, 포인터 이동 조건(while) 실수.",
        "items": ["현재의 선택이 항상 최선임을 증명했는가?(그리디)", "Left/Right 포인터가 역전되는 조건을 명확히 설정했는가?"]
    },
    "이진 탐색": {
        "mistakes": "무한 루프(mid 계산 방식), 정렬되지 않은 배열에서 탐색 시도.",
        "items": ["배열이 오름차순으로 정렬되어 있는가?", "low = mid + 1, high = mid - 1 처리를 정확히 했는가?"]
    },
    "시뮬레이션": {
        "mistakes": "조건 누락, 2차원 배열 복사 시 깊은 복사(deepcopy) 미사용.",
        "items": ["문제의 모든 제약 조건을 리스트업하고 하나씩 지워나갔는가?", "원본 배열을 보존해야 할 때 copy()를 적절히 사용했는가?"]
    },
    "DP": {
        "mistakes": "점화식 오류, 초기값(Base Case) 설정 미흡.",
        "items": ["가장 작은 문제의 답(dp[0], dp[1])을 직접 손으로 계산해 보았는가?", "Memoization을 통해 중복 계산을 막았는가?"]
    },
    "다익스트라": {
        "mistakes": "우선순위 큐(heapq)에 (거리, 노드) 순서가 아닌 잘못된 순서 삽입.",
        "items": ["방문한 노드를 다시 처리하지 않도록 최단 거리 테이블을 확인했는가?", "가중치가 음수인 간선이 없는지 확인했는가?"]
    }
}

for sp in subpages:
    page_id = sp["id"]
    title = sp["child_page"]["title"]
    
    # Matching title to our templates
    matched = False
    for key in checklists:
        if key in title:
            append_checklist(page_id, title, checklists[key]["items"], checklists[key]["mistakes"])
            print(f"Updated checklist for: {title}")
            matched = True
            break
    if not matched:
        print(f"Skipping or need custom logic for: {title}")

print("All applicable algorithm pages have been updated with checklists.")
