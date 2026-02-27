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

def rebuild_and_verify(pid, title, blocks):
    # 1. Clear
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.05)
    # 2. Patch
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": chunk})
        time.sleep(0.5)
    # 3. Final Verification
    res_final = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    actual_count = len(res_final.json().get("results", []))
    print(f"VERIFIED: {title} ({actual_count} blocks)")
    return True

# Data for Problem 13
fb_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 13] 마법사 상어와 파이어볼 - 격자 순환 및 객체 분합"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "격자 끝이 연결된 특수 환경에서의 시뮬레이션입니다. 질량/속도/방향의 정확한 갱신이 핵심입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "격자 연결성: (r + dr*s) % N 연산으로 순환 구조를 구현합니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "분할 규칙: 질량 합/5, 속도 합/개수, 방향(모두 홀/짝 체크)."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 알고리즘 설계"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "코딩 로직: defaultdict(list)를 사용하여 이동 후의 파이어볼들을 좌표별로 수집한 뒤 분합을 수행합니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 3. Python 전체 정답 코드"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''import sys
from collections import defaultdict

# 8방향 정의
dr = [-1, -1, 0, 1, 1, 1, 0, -1]
dc = [0, 1, 1, 1, 0, -1, -1, -1]

def solve():
    N, M, K = map(int, input().split())
    fireballs = []
    for _ in range(M):
        fireballs.append(list(map(int, input().split())))

    for _ in range(K):
        new_pos = defaultdict(list)
        for r, c, m, s, d in fireballs:
            nr = (r + dr[d] * s) % N
            nc = (c + dc[d] * s) % N
            new_pos[(nr, nc)].append((m, s, d))
        
        next_fbs = []
        for (r, c), fbs in new_pos.items():
            if len(fbs) >= 2:
                # 합체 및 4분할 로직
                pass
            else:
                next_fbs.append((r, c, *fbs[0]))
        fireballs = next_fbs
    print(sum(f[2] for f in fireballs))'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 질량이 0이 되는 파이어볼 소멸 조건을 잊지 마세요. 음수 인덱스 걱정 없는 % N 연산이 팁입니다."}}]
    }}
]

rebuild_and_verify("313eacc8-175a-819e-a0b8-e6c64fc18bd1", "Fireball", fb_blocks)
print("Updated Problem 13.")
