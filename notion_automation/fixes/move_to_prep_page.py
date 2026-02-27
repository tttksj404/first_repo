import requests
import time
import json


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
PREP_PAGE_ID = '303eacc8-175a-80a3-9154-f7a7acee7c80'
HEADERS = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Content-Type': 'application/json',
    'Notion-Version': '2022-06-28'
}

def split_text(text, limit=1900):
    return [text[i:i+limit] for i in range(0, len(text), limit)]

def create_problem_page(title, content_blocks):
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"page_id": PREP_PAGE_ID},
        "properties": {
            "title": {"title": [{"text": {"content": title}}]}
        }
    }
    res = requests.post(url, headers=HEADERS, json=payload)
    if res.status_code != 200:
        print(f"Failed to create page {title}: {res.text}")
        return None
    page_id = res.json()["id"]
    print(f"Created page: {title} (ID: {page_id})")
    
    # Append content to the new page
    append_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    for i in range(0, len(content_blocks), 5):
        chunk = content_blocks[i:i+5]
        res_patch = requests.patch(append_url, headers=HEADERS, json={"children": chunk})
        if res_patch.status_code != 200:
            print(f"Failed to append content to {title}: {res_patch.text}")
        time.sleep(1)
    return page_id

# Content for Monster Hunter
monster_hunter_code = """import sys

def get_dist(p1, p2):
    return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])

def backtrack(curr_pos, visited_mask, picked_mask, time):
    global min_time
    if time >= min_time: return
    if visited_mask == (1 << (2 * M)) - 1:
        min_time = min(min_time, time)
        return

    for i in range(2 * M):
        if not (visited_mask & (1 << i)):
            if i < M: # 몬스터 방문
                backtrack(targets[i], visited_mask | (1 << i), picked_mask | (1 << i), 
                          time + get_dist(curr_pos, targets[i]))
            else: # 고객 방문 (선행 몬스터 사냥 여부 확인)
                if picked_mask & (1 << (i - M)):
                    backtrack(targets[i], visited_mask | (1 << i), picked_mask, 
                              time + get_dist(curr_pos, targets[i]))

T = int(input())
for tc in range(1, T + 1):
    N = int(input())
    matrix = [list(map(int, input().split())) for _ in range(N)]
    m_pos, c_pos = {}, {}
    for r in range(N):
        for c in range(N):
            if matrix[r][c] > 0: m_pos[matrix[r][c]] = (r, c)
            elif matrix[r][c] < 0: c_pos[abs(matrix[r][c])] = (r, c)
    M = len(m_pos)
    targets = [m_pos[i] for i in range(1, M+1)] + [c_pos[i] for i in range(1, M+1)]
    min_time = float('inf')
    backtrack((0, 0), 0, 0, 0)
    print(f"#{tc} {min_time}")
"""

monster_hunter_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "📍 [Samsung A] 몬스터 헌터 - 비트마스크 백트래킹"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"text": {"content": "순열(Permutation) 구조에 선행 조건이 결합된 문제입니다. 비트마스크를 활용해 방문 상태를 관리하고, 고객 방문 전 몬스터 사냥 여부를 체크하는 것이 핵심입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🔍 1. 문제 상황 상세 분석"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "상태 관리: visited_mask(방문한 곳)와 picked_mask(몬스터 확보) 2종류 사용."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "선행 조건: 특정 번호의 몬스터를 처리해야만 해당 번호의 고객 방문 가능."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "💻 2. Python 정답 코드 (상세 주석)"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"text": {"content": chunk}} for chunk in split_text(monster_hunter_code)]}},
    {"type": "callout", "callout": {"icon": {"emoji": "💡"}, "rich_text": [{"text": {"content": "학생 가이드: 비트마스크 백트래킹은 N이 작을 때(M<=5) 사용하는 필살기입니다. 시간 초과를 막기 위해 기저 조건에서의 min_time 갱신과 중간 가지치기를 잊지 마세요."}}]}}
]

# Content for Prerequisite Subjects
prerequisite_code = """from collections import deque

T = int(input())
for tc in range(1, T + 1):
    N = int(input())
    adj = [[] for _ in range(N + 1)]
    in_degree = [0] * (N + 1)
    for i in range(1, N + 1):
        data = list(map(int, input().split()))
        if data[0] > 0:
            for pre in data[1:]:
                adj[pre].append(i)
                in_degree[i] += 1
    
    queue = deque([i for i in range(1, N + 1) if in_degree[i] == 0])
    semester, done = 0, 0
    while queue:
        semester += 1
        for _ in range(len(queue)):
            curr = queue.popleft()
            done += 1
            for nxt in adj[curr]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)
    
    print(f"#{tc} {semester if done == N else -1}")
"""

prerequisite_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "📍 [Samsung A] 학교 필수 과목 - 위상 정렬"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"text": {"content": "과목 간 선후 관계가 명확한 전형적인 위상 정렬 문제입니다. 한 학기에 무제한 수강이 가능하므로 큐의 레벨 단위(Level-based) 탐색이 필요합니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🔍 1. 핵심 구현 로직"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "진입 차수(In-degree): 선수 과목의 개수를 관리하여 0이 되는 순간 큐에 삽입."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "레벨링(Leveling): 한 학기 동안 들을 수 있는 과목은 큐의 현재 사이즈(len(queue))만큼 반복 처리하여 학기 수를 계산."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "💻 2. Python 정답 코드"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"text": {"content": chunk}} for chunk in split_text(prerequisite_code)]}},
    {"type": "callout", "callout": {"icon": {"emoji": "🎓"}, "rich_text": [{"text": {"content": "학생 가이드: 위상 정렬은 선후 관계가 있을 때 무조건 0순위로 떠올리세요! 사이클이 생기면 done != N 조건을 통해 -1을 출력하는 예외 처리가 필수입니다."}}]}}
]

if __name__ == "__main__":
    create_problem_page("📍 [Samsung A] 몬스터 헌터 (비트마스크 백트래킹)", monster_hunter_blocks)
    create_problem_page("📍 [Samsung A] 학교 필수 과목 (위상 정렬)", prerequisite_blocks)
