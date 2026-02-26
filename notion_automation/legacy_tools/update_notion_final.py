import requests
import json

NOTION_TOKEN = "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"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PAGE_ID = "2f0eacc8-175a-805c-85b2-dca59899d3d8"

# 1. Fetch blocks
url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
blocks = []
has_more = True
next_cursor = None
while has_more:
    params = {}
    if next_cursor:
        params["start_cursor"] = next_cursor
    res = requests.get(url, headers=HEADERS, params=params)
    data = res.json()
    blocks.extend(data.get("results", []))
    has_more = data.get("has_more", False)
    next_cursor = data.get("next_cursor")

# 2. Find bad blocks to delete
bad_texts = [
    "📍 [Problem 03]",
    "> 상황: 수빈이",
    "현실의 생각:",
    "코딩 변환:",
    "[Python Code Implementation]",
    "from collections import deque",
    "💡 학생의 가이드",
    "💡 학생 가이드",
    "[Python 핵심 로직]",
    "while queue:",
    "▶ 상황: N에서 K로",
    "--------------------------------------------------"
]

blocks_to_delete = []
for b in blocks:
    b_type = b["type"]
    b_obj = b.get(b_type, {})
    if "rich_text" in b_obj:
        text_content = "".join([rt.get("text", {}).get("content", "") for rt in b_obj["rich_text"]])
        if any(bad in text_content for bad in bad_texts):
            blocks_to_delete.append(b["id"])

print(f"Found {len(blocks_to_delete)} bad blocks to delete.")
for bid in blocks_to_delete:
    requests.delete(f"https://api.notion.com/v1/blocks/{bid}", headers=HEADERS)

# 3. Find the TOC block or the first block to insert after
insert_after_id = None
# We want to insert after the TOC (table_of_contents) if it exists, or maybe after the first block.
# Let's search for TOC or Callout
for b in blocks:
    if b["type"] == "table_of_contents":
        insert_after_id = b["id"]
        break

# If not found, let's insert after the Callout with "💡 학생의 가이드: 기존 내용을 정독한 뒤" 
# or just top of page.
if not insert_after_id:
    for b in blocks:
        if b["type"] == "callout":
            text_content = "".join([rt.get("text", {}).get("content", "") for rt in b.get("callout", {}).get("rich_text", [])])
            if "기존 내용을 정독한 뒤" in text_content:
                insert_after_id = b["id"]
                break

if not insert_after_id and len(blocks) > 0:
    insert_after_id = blocks[0]["id"]

# 4. Insert beautiful blocks
blocks_to_insert = [
    {
        "object": "block",
        "type": "divider",
        "divider": {}
    },
    {
        "object": "block",
        "type": "heading_3",
        "heading_3": {
            "rich_text": [{"type": "text", "text": {"content": "📍 [Problem 03] 숨바꼭질 (1D BFS & 최단 시간 측정)"}}]
        }
    },
    {
        "object": "block",
        "type": "quote",
        "quote": {
            "rich_text": [{"type": "text", "text": {"content": "상황: 수빈이(N)가 동생(K)을 찾기 위해 -1, +1, *2로 이동할 때, 가장 빨리 동생을 만나는 시간(초)은 얼마인가?"}}]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "현실의 생각: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "\"지금 내 위치에서 갈 수 있는 3가지 길을 모두 확인해보고, 그곳에서도 또 3가지 길을 확인하면서 동생이 보일 때까지 물결처럼 퍼져나가자.\""}}
            ]
        }
    },
    {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [
                {"type": "text", "text": {"content": "코딩 변환: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "큐(Queue)에 현재 위치를 넣고, 꺼낼 때마다 (c-1, c+1, c*2)를 계산하여 방문하지 않은 곳이면 '현재 시간 + 1'을 기록하며 전진한다. (BFS의 레벨 탐색)"}}
            ]
        }
    },
    {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": "[Python Code Implementation]"}, "annotations": {"bold": True}}]
        }
    },
    {
        "object": "block",
        "type": "code",
        "code": {
            "language": "python",
            "rich_text": [{"type": "text", "text": {"content": '''from collections import deque

def bfs(start, end):
    # 시작과 동시에 도착한 경우 처리
    if start == end: return 0
    
    # [Visited] 최대 범위 100,000까지 고려하여 리스트 생성
    MAX_SIZE = 100001
    visited = [0] * MAX_SIZE
    
    queue = deque([start])
    visited[start] = 1 # 시작점 방문 표시 (결과에서 1 빼기 방식)

    while queue:
        current = queue.popleft()

        # 이동 가능한 3가지 위치 탐색
        for neighbor in (current-1, current+1, current*2):
            # 1. 인덱스 범위 내에 있고 2. 아직 방문하지 않은 경우
            if 0 <= neighbor < MAX_SIZE and visited[neighbor] == 0:
                visited[neighbor] = visited[current] + 1
                
                if neighbor == end:
                    return visited[neighbor] - 1 # 도착! 기록된 시간 반환
                
                queue.append(neighbor)
    return -1

N, K = map(int, input().split())
print(bfs(N, K))'''}}]
        }
    },
    {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "💡"},
            "color": "blue_background",
            "rich_text": [
                {"type": "text", "text": {"content": "학생의 가이드: "}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "count 변수를 따로 만들어서 pop할 때마다 1씩 더하면 절대 안 됩니다! 그렇게 하면 '전체 탐색 횟수'를 세게 되어 오답이 나옵니다. 반드시 "}},
                {"type": "text", "text": {"content": "visited[next] = visited[curr] + 1"}, "annotations": {"code": True, "bold": True, "color": "red"}},
                {"type": "text", "text": {"content": " 공식을 사용하여 '각 위치까지의 깊이(시간)'를 기록하세요."}}
            ]
        }
    },
    {
        "object": "block",
        "type": "divider",
        "divider": {}
    }
]

payload = {
    "children": blocks_to_insert
}
if insert_after_id:
    payload["after"] = insert_after_id

patch_url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
res = requests.patch(patch_url, headers=HEADERS, json=payload)
if res.status_code == 200:
    print("Successfully inserted formatted blocks.")
else:
    print("Failed:", res.status_code, res.text)
