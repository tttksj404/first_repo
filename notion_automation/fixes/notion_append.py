import requests
import json
import time
import os

def _get_notion_token():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(current_dir, '..', 'core', 'notion_key.txt'),
        os.path.join(os.getcwd(), 'notion_automation', 'core', 'notion_key.txt')
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return f.read().strip()
    return os.getenv("NOTION_TOKEN")

NOTION_TOKEN = _get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PAGE_ID = "2f0eacc8-175a-805c-85b2-dca59899d3d8"

def read_file_safe(path):
    if not os.path.exists(path):
        return f"# Error: File not found at {path}"
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

# Problems to append
probs = [
    {
        "num": "01",
        "title": "1926 - 그림 (BFS 영역 탐색 기초)",
        "file": "gitp/BFS/1926델타응용 bfs2.py",
        "desc": "2차원 배열에서 연결된 1의 개수와 최대 넓이를 구하는 전형적인 BFS 입문 문제입니다."
    },
    {
        "num": "03",
        "title": "2667 - 단지번호붙이기 (연결 요소 정렬)",
        "file": "gitp/BFS/2667.py",
        "desc": "연결된 단지별 집의 개수를 구하고, 그 결과를 오름차순으로 정렬하여 출력하는 정렬 응용 BFS입니다."
    },
    {
        "num": "04",
        "title": "9205 - 맥주 마시며 걸어가기 (거리 기반 BFS)",
        "file": "gitp/BFS/9205.py",
        "desc": "상하좌우 탐색이 아닌, 모든 지점 간의 '맨해튼 거리'를 계산하여 이동 가능 여부를 판단하는 좌표 BFS입니다."
    }
]

new_blocks = []

for p in probs:
    code_content = read_file_safe(p["file"])
    new_blocks.extend([
        {"type": "divider", "divider": {}},
        {"type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": f"📍 [Problem {p['num']}] {p['title']}"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": p['desc']}}]}},
        {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": code_content[:2000]}}]}}
    ])

# Patch (Append) children
url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
res = requests.patch(url, headers=HEADERS, json={"children": new_blocks})

if res.status_code == 200:
    print("Successfully appended problems to the existing page in the correct format.")
else:
    print(f"Failed to append: {res.text}")
