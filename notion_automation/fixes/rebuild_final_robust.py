import requests
import json
import time


import os

def _get_notion_token():
    # Try multiple paths to find notion_key.txt
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(current_dir, 'notion_key.txt'),
        os.path.join(current_dir, '..', 'core', 'notion_key.txt'),
        os.path.join(current_dir, 'core', 'notion_key.txt'),
        os.path.join(os.getcwd(), 'notion_automation', 'core', 'notion_key.txt')
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                token = f.read().strip()
                if token: return token
    return os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")

NOTION_TOKEN = _get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def rebuild_final_robust(pid, blocks):
    # Clear
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
    # Patch
    res_patch = requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": blocks})
    return res_patch.status_code

# Problem 06 - Pop
pop_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 06] 인구 이동 - BFS 영역 탐색 및 인구 재분배"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "인구 차이에 따라 국경을 열고 연합을 형성하는 시뮬레이션입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 핵심 알고리즘 설계"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "현실 로직: 이웃 나라와 인구 차가 적절하면 국경 개방! 연합 인구 합산 후 평균화."}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": "if L <= abs(grid[r][c] - grid[nr][nc]) <= R: pass"}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 매일 전체 맵을 돌며 방문하지 않은 곳마다 BFS를 시도하세요."}}]
    }}
]

# Problem 07 - Fish
fish_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 07] 낚시왕 - 속도 최적화 및 격자 시뮬레이션"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "상어의 빠른 속도를 나머지 연산으로 최적화하는 것이 필수입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 핵심 알고리즘 설계"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "이동 최적화: speed %= (2*(N-1)) 공식을 적용해 연산량을 줄입니다."}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": "speed %= (2 * (N - 1))"}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 모든 상어 이동 후 같은 칸 충돌 처리를 위해 새 맵을 사용하세요."}}]
    }}
]

print("Pop:", rebuild_final_robust("313eacc8-175a-817a-b91e-fc823a0ab988", pop_blocks))
print("Fish:", rebuild_final_robust("313eacc8-175a-81cd-abb4-cd3ada7df20e", fish_blocks))
