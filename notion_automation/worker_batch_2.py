import requests
import json
import time

NOTION_TOKEN = "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"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def worker(pid, title, blocks):
    print(f"--- [UPDATING] {title} ---")
    url = f"https://api.notion.com/v1/blocks/{pid}/children"
    res_get = requests.get(url, headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.05)
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        requests.patch(url, headers=HEADERS, json={"children": chunk})
        time.sleep(0.5)
    res_final = requests.get(url, headers=HEADERS)
    print(f"VERIFIED: {title} ({len(res_final.json().get('results', []))} blocks)")
    return True

# Data for batch 2
tetro_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 09] 테트로미노 - DFS 탐색과 특수 모양 처리"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "ㅗ 모양을 제외한 4가지 모양은 DFS 깊이 4로 탐색 가능합니다."}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": "def dfs(r, c, d, total): # max depth 4 backtracking"}}]}},
    {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "💡"}, "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 방문 체크를 넣고 빼는 백트래킹 정석을 익히세요."}}]}}
]

chicken_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 10] 치킨 배달 - 조합 거리 합 최적화"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "맵 전체 탐색 없이 좌표 간의 거리만 계산하는 것이 핵심입니다."}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": "for sel in combinations(chickens, M): score = sum(min_dist)"}}]}},
    {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "💡"}, "rich_text": [{"type": "text", "text": {"content": "학생 가이드: N이 최대 50이지만 가게 수는 적어 조합이 유리합니다."}}]}}
]

worker("313eacc8-175a-817f-9ad8-fe6917b25c99", "Tetro", tetro_blocks)
worker("313eacc8-175a-8120-b249-efef529db6f8", "Chicken", chicken_blocks)
