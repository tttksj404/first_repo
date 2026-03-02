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
PARENT_PAGE_ID = "2f0eacc8-175a-805c-85b2-dca59899d3d8"

def read_file_safe(path):
    if not os.path.exists(path):
        return f"Error: File not found at {path}"
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

# 1926, 2667, 9205
problems = [
    {
        "title": "📍 [BFS] 1926 - 그림 (영역 탐색)",
        "file": "gitp/BFS/1926델타응용 bfs2.py",
        "desc": "그림의 개수와 가장 큰 그림의 넓이를 구하는 BFS 기초"
    },
    {
        "title": "📍 [BFS/DFS] 2667 - 단지번호붙이기",
        "file": "gitp/BFS/2667.py",
        "desc": "연결된 단지별 집의 개수를 구하고 정렬하여 출력"
    },
    {
        "title": "📍 [BFS] 9205 - 맥주 마시며 걸어가기",
        "file": "gitp/BFS/9205.py",
        "desc": "좌표 기반 BFS로 거리 1000m 이내 이동 가능 여부 판별"
    }
]

created_info = []

for prob in problems:
    content = read_file_safe(prob["file"])
    data = {
        "parent": {"page_id": PARENT_PAGE_ID},
        "properties": {
            "title": {"title": [{"text": {"content": prob["title"]}}]}
        },
        "children": [
            {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": prob["title"]}}]}},
            {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": prob["desc"]}}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 Python 전체 코드"}}]}},
            {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": content[:2000]}}]}} # 내용 길 경우를 대비해 슬라이싱 (실제 2000자 넘지 않음)
        ]
    }
    
    res = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json=data)
    if res.status_code == 200:
        res_json = res.json()
        created_info.append({
            "title": prob["title"],
            "id": res_json["id"],
            "url": res_json["url"]
        })
    else:
        created_info.append({
            "title": prob["title"],
            "error": res.text
        })
    time.sleep(1)

print(json.dumps(created_info, indent=2, ensure_ascii=False))
