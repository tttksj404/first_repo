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
PAGE_ID = '2f0eacc8-175a-805c-85b2-dca59899d3d8'
HEADERS = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Content-Type': 'application/json',
    'Notion-Version': '2022-06-28'
}

def split_text(text, limit=1900):
    return [text[i:i+limit] for i in range(0, len(text), limit)]

def update_notion_a_type():
    # -------------------------------------------------------------------------
    # Problem 1: Monster Hunter
    # -------------------------------------------------------------------------
    monster_hunter_code = """import sys

# 두 지점 사이의 이동 시간을 맨해튼 거리로 계산하는 함수
def get_dist(p1, p2):
    return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])

def backtrack(curr_pos, visited_mask, picked_mask, time):
    global min_time
    
    # [가지치기] 현재 시간이 이미 알고 있는 최소 시간보다 크면 더 볼 필요 없음
    if time >= min_time: 
        return
    
    # [기저 조건] 모든 몬스터와 모든 고객을 방문했다면 최소 시간 갱신
    # 2 * M개의 비트가 모두 1인 상태 확인
    if visited_mask == (1 << (2 * M)) - 1:
        min_time = min(min_time, time)
        return

    for i in range(2 * M):
        # i번째 목표물을 아직 방문하지 않았다면
        if not (visited_mask & (1 << i)):
            if i < M: # 몬스터 방문 (0 ~ M-1 index)
                # 몬스터는 언제든 잡을 수 있으므로 즉시 방문
                backtrack(targets[i], 
                          visited_mask | (1 << i), 
                          picked_mask | (1 << i), 
                          time + get_dist(curr_pos, targets[i]))
            else: # 고객 방문 (M ~ 2M-1 index)
                # [선행 조건 확인] 반드시 i-M 번호의 몬스터를 먼저 처리했어야 함
                if picked_mask & (1 << (i - M)):
                    backtrack(targets[i], 
                              visited_mask | (1 << i), 
                              picked_mask, 
                              time + get_dist(curr_pos, targets[i]))

# 테스트 케이스 개수 입력
T = int(input())
for tc in range(1, T + 1):
    N = int(input()) # 지도 크기
    matrix = [list(map(int, input().split())) for _ in range(N)]
    
    m_pos, c_pos = {}, {}
    for r in range(N):
        for c in range(N):
            if matrix[r][c] > 0: # 몬스터 위치 저장
                m_pos[matrix[r][c]] = (r, c)
            elif matrix[r][c] < 0: # 고객 위치 저장
                c_pos[abs(matrix[r][c])] = (r, c)
    
    M = len(m_pos) # 몬스터의 총 개수
    # targets 리스트: [몬스터1, 몬스터2, ..., 고객1, 고객2, ...] 순서로 구성
    targets = [m_pos[i] for i in range(1, M+1)] + [c_pos[i] for i in range(1, M+1)]
    
    min_time = float('inf')
    # 시작 위치 (0, 0), 초기 방문/습득 마스크 0에서 백트래킹 시작
    backtrack((0, 0), 0, 0, 0)
    print(f"#{tc} {min_time}")
"""

    # -------------------------------------------------------------------------
    # Problem 2: Prerequisite Subjects
    # -------------------------------------------------------------------------
    prerequisite_code = """from collections import deque

# 테스트 케이스 개수 입력
T = int(input())
for tc in range(1, T + 1):
    N = int(input()) # 과목 수
    adj = [[] for _ in range(N + 1)] # 인접 리스트 (선수 과목 -> 다음 과목)
    in_degree = [0] * (N + 1) # 진입 차수 배열 (선수 과목의 개수)
    
    for i in range(1, N + 1):
        data = list(map(int, input().split()))
        if data[0] > 0: # 선수 과목이 있다면
            # data[0]은 선수 과목 개수, data[1:]은 과목 리스트
            for pre in data[1:]:
                adj[pre].append(i) # 선수 과목이 끝나면 i 과목을 들을 수 있음
                in_degree[i] += 1  # i 과목의 진입 차수 증가
    
    # 진입 차수가 0인 과목(선수 과목이 없는 과목)을 큐에 삽입
    queue = deque([i for i in range(1, N + 1) if in_degree[i] == 0])
    
    semester, done = 0, 0
    while queue:
        semester += 1 # 한 학기 시작
        # 현재 큐에 있는 모든 과목은 동시에 이번 학기에 수강 가능
        for _ in range(len(queue)):
            curr = queue.popleft()
            done += 1 # 이수 완료 처리
            
            # 현재 과목을 이수했으므로, 이 과목을 선수 과목으로 하는 다음 과목들 확인
            for nxt in adj[curr]:
                in_degree[nxt] -= 1 # 선수 과목 하나 완료
                # 모든 선수 과목을 다 들었다면 다음 학기에 수강 가능하도록 큐에 삽입
                if in_degree[nxt] == 0:
                    queue.append(nxt)
    
    # 모든 과목을 이수했다면 소요 학기 출력, 사이클 등으로 불가능하면 -1
    print(f"#{tc} {semester if done == N else -1}")
"""

    # -------------------------------------------------------------------------
    # Blocks Construction
    # -------------------------------------------------------------------------
    blocks = [
        {'type': 'divider', 'divider': {}},
        {'type': 'heading_1', 'heading_1': {'rich_text': [{'type': 'text', 'text': {'content': '🏆 [Samsung A] 기출 분석: 몬스터 헌터 & 필수 과목'}}]}},
        {'type': 'quote', 'quote': {'rich_text': [{'type': 'text', 'text': {'content': '삼성 A형 합격의 필수 알고리즘인 백트래킹(Bitmask)과 위상 정렬(Topological Sort)을 완벽히 정리합니다.'}}]}},
        
        # Monster Hunter Section
        {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '📍 [Problem 05] 몬스터 헌터 - 비트마스크 백트래킹'}}]}},
        {'type': 'paragraph', 'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': '순열(Permutation) 구조에 선행 조건이 결합된 문제입니다. 비트마스크를 활용해 방문 상태를 관리하고, 고객 방문 전 몬스터 사냥 여부를 체크하는 것이 핵심입니다.'}}]}},
        {'type': 'heading_3', 'heading_3': {'rich_text': [{'type': 'text', 'text': {'content': '🏗️ 구현 포인트'}}]}},
        {'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'type': 'text', 'text': {'content': '상태 관리: visited_mask(방문한 곳)와 picked_mask(몬스터 확보) 2종류 사용.'}}]}},
        {'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'type': 'text', 'text': {'content': '조건 체크: i >= M(고객)일 때 picked_mask & (1 << (i-M)) 검사.'}}]}},
        {'type': 'code', 'code': {'language': 'python', 'rich_text': [{"type": "text", "text": {"content": chunk}} for chunk in split_text(monster_hunter_code)]}},
        
        # Prerequisite Subjects Section
        {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '📍 [Problem 06] 학교 필수 과목 - 위상 정렬'}}]}},
        {'type': 'paragraph', 'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': '과목 간 선후 관계가 명확한 전형적인 위상 정렬 문제입니다. 한 학기에 무제한 수강이 가능하므로 큐의 레벨 단위(Level-based) 탐색이 필요합니다.'}}]}},
        {'type': 'heading_3', 'heading_3': {'rich_text': [{'type': 'text', 'text': {'content': '🏗️ 구현 포인트'}}]}},
        {'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'type': 'text', 'text': {'content': '진입 차수(In-degree): 선수 과목의 개수를 관리하여 0이 되는 순간 큐에 삽입.'}}]}},
        {'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'type': 'text', 'text': {'content': '학기 카운트: while 루프 한 번 돌 때마다 semester를 증가시켜 학기 계산.'}}]}},
        {'type': 'code', 'code': {'language': 'python', 'rich_text': [{"type": "text", "text": {"content": chunk}} for chunk in split_text(prerequisite_code)]}},
        
        {'type': 'callout', 'callout': {'icon': {'type': 'emoji', 'emoji': '🎓'}, 'rich_text': [{'type': 'text', 'text': {'content': '학생 가이드: 비트마스크 백트래킹은 N이 작을 때(M<=5) 사용하는 필살기입니다. 위상 정렬은 선후 관계가 있을 때 무조건 0순위로 떠올리세요!'}}]}}
    ]

    # -------------------------------------------------------------------------
    # Update Execution
    # -------------------------------------------------------------------------
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    print(f"Updating page with {len(blocks)} blocks using 2-stage chunking...")
    
    for i in range(0, len(blocks), 5):
        chunk = blocks[i:i+5]
        res = requests.patch(url, headers=HEADERS, json={'children': chunk})
        if res.status_code == 200:
            print(f"Chunk {i//5 + 1} appended.")
        else:
            print(f"Error at chunk {i//5 + 1}: {res.text}")
            return False
        time.sleep(1)
    
    print("SUCCESS: A-type problem analysis updated.")
    return True

if __name__ == "__main__":
    update_notion_a_type()
