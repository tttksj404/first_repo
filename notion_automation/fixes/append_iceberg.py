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

blocks = [
    {'type': 'divider', 'divider': {}},
    {'type': 'heading_1', 'heading_1': {'rich_text': [{'type': 'text', 'text': {'content': '📍 [Samsung A] 빙산 - BFS 기반 동시 시뮬레이션 및 최적화'}}]}},
    {'type': 'quote', 'quote': {'rich_text': [{'type': 'text', 'text': {'content': '빙산이 매년 주변 바다의 개수만큼 녹아내리며, 두 덩어리 이상으로 분리되는 최초의 시간을 구하는 문제입니다. 맵 전체를 탐색하는 대신 빙산의 좌표만 관리하여 효율성을 극대화하는 것이 핵심입니다.'}}]}},
    {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '🔍 1. 문제 상황 상세 분석 (IM 초월)'}}]}},
    {'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'type': 'text', 'text': {'content': '시간 초과 주의: 300x300 맵을 매년 전수 조사(90,000칸)하는 대신, 빙산의 좌표만 담은 ice_list를 활용해 효율을 극대화합니다.'}}]}},
    {'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'type': 'text', 'text': {'content': '동시성 처리 (스냅샷): 빙산이 녹는 도중에 맵을 수정하면 옆 칸 계산이 꼬입니다. melt_list에 예약 정보를 담아 한꺼번에 처리하는 Batch Update가 필수입니다.'}}]}},
    {'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'type': 'text', 'text': {'content': '다이어트 기법: 매년 녹아서 사라진 빙산은 명단에서 즉시 제거하여, 시간이 갈수록 연산량이 줄어들게 설계합니다.'}}]}},
    {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '🏗️ 2. 구현 체크리스트'}}]}},
    {'type': 'to_do', 'to_do': {'checked': True, 'rich_text': [{'type': 'text', 'text': {'content': 'ice_list 초기화: 0보다 큰 빙산 위치 모두 저장'}}]}},
    {'type': 'to_do', 'to_do': {'checked': True, 'rich_text': [{'type': 'text', 'text': {'content': 'count_chunks 함수: BFS로 연결된 덩어리 개수 파악'}}]}},
    {'type': 'to_do', 'to_do': {'checked': True, 'rich_text': [{'type': 'text', 'text': {'content': '녹이기 예약: 사방의 0 개수 카운트 후 melt_list 저장'}}]}},
    {'type': 'to_do', 'to_do': {'checked': True, 'rich_text': [{'type': 'text', 'text': {'content': '일괄 업데이트: max(0, ice[r][c] - sea) 적용 및 명단 갱신'}}]}},
    {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '💻 3. Python 전체 정답 코드'}}]}},
    {'type': 'code', 'code': {'language': 'python', 'rich_text': [{'type': 'text', 'text': {'content': """from collections import deque
import sys
input = sys.stdin.readline

N, M = map(int, input().split())
ice = []
ice_list = [] # 빙산의 위치를 담은 '쪽지'

for i in range(N):
    row = list(map(int, input().split()))
    ice.append(row)
    for j in range(M):
        if row[j] > 0:
            ice_list.append((i, j))

dr = [-1, 1, 0, 0]
dc = [0, 0, -1, 1]

def count_chunks(current_ice):
    visited = [[False] * M for _ in range(N)]
    chunks = 0
    for r, c in current_ice:
        if ice[r][c] > 0 and not visited[r][c]:
            q = deque([(r, c)])
            visited[r][c] = True
            while q:
                curr_r, curr_c = q.popleft()
                for i in range(4):
                    nr, nc = curr_r + dr[i], curr_c + dc[i]
                    if ice[nr][nc] > 0 and not visited[nr][nc]:
                        visited[nr][nc] = True
                        q.append((nr, nc))
            chunks += 1
    return chunks

year = 0
while ice_list:
    num = count_chunks(ice_list)
    if num >= 2:
        print(year)
        break
    
    melt_list = []
    for r, c in ice_list:
        sea = 0
        for i in range(4):
            nr, nc = r + dr[i], c + dc[i]
            if ice[nr][nc] == 0:
                sea += 1
        if sea > 0: 
            melt_list.append((r, c, sea))
    
    for r, c, amount in melt_list:
        ice[r][c] = max(0, ice[r][c] - amount)
    
    next_ice_list = []
    for r, c in ice_list:
        if ice[r][c] > 0:
            next_ice_list.append((r, c))
            
    ice_list = next_ice_list
    year += 1
else:
    print(0)"""}}]}},
    {'type': 'callout', 'callout': {'icon': {'type': 'emoji', 'emoji': '💡'}, 'rich_text': [{'type': 'text', 'text': {'content': '학생 가이드: "범인은 이 안에 있어!" 기법을 기억하세요. 9만 개의 칸을 매번 도는 대신 수백 개의 빙산 좌표만 들고 뛰는 것이 A형 합격의 지름길입니다. 또한 "스냅샷(예약 시스템)"을 통해 데이터 오염을 막는 습관이 중요합니다.'}}]}}
]

def append_blocks(page_id, blocks):
    url = f'https://api.notion.com/v1/blocks/{page_id}/children'
    for i in range(0, len(blocks), 5):
        chunk = blocks[i:i+5]
        attempt = 0
        while attempt < 5:
            res = requests.patch(url, headers=HEADERS, json={'children': chunk})
            if res.status_code == 200:
                print(f'Chunk {i//5 + 1} appended successfully.')
                break
            elif res.status_code == 429 or res.status_code >= 500:
                wait = 2 ** attempt
                print(f'Rate limited or Server error. Retrying in {wait}s...')
                time.sleep(wait)
                attempt += 1
            else:
                print(f'Failed to append chunk {i//5 + 1}: {res.text}')
                return
        time.sleep(1)

if __name__ == '__main__':
    append_blocks(PAGE_ID, blocks)
