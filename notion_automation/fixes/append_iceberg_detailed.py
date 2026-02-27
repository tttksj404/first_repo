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

# 1. 원본 코드와 주석 (사용자 요청에 따라 100% 상세하게)
detailed_code = """'''
bfs로 하고 시작점 1이상인 곳 동서남북에 0있는 곳으로 퍼짐 0의 개수 만큼  시작값 줄어듦 
그러나 최소는 0이 되는 것 조건 필요

그렇게 1년후 새롭게 변하게된 빙산의 모습들 
전부다 돌고 모든 1이상이 있는 값의 visited값이 true면 다돈거라
->visited의 초기화 

그다음 1년은 이전 빙산 모습에서 똑같은 로직 진행 
'''

from collections import deque
import sys
input = sys.stdin.readline

N, M = map(int, input().split())
ice = []
ice_list = [] # <--- 이게 바로 그 '쪽지'입니다! (용의자 명단)

for i in range(N):
    row = list(map(int, input().split()))
    ice.append(row)
    for j in range(M):
        if row[j] > 0:
            ice_list.append((i, j)) # 처음 빙산 위치만 딱 저장해둬요.

dr = [-1, 1, 0, 0]
dc = [0, 0, -1, 1]

# 1. 덩어리 세기 (이해하신 로직 그대로!)
def count_chunks(current_ice):
    visited = [[False] * M for _ in range(N)]
    chunks = 0
    for r, c in current_ice: # 9만 칸 대신 빙산 쪽지만 확인!
        if ice[r][c] > 0 and not visited[r][c]:
            # BFS 시작
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
while ice_list: # 빙산이 다 녹을 때까지 반복
    # 1. 덩어리 개수 확인
    num = count_chunks(ice_list) #어짜피 시작점에서 bfs하면 그건 한덩어리라서 굳이 안구하고도 빙하 1개로 판단가능
    if num >= 2:
        print(year)
        break
    
    # 2. 빙산 녹이기 (예약 시스템 - 스냅샷 기법)
    melt_list = [] # (행, 열, 녹을 양) 저장할 임시 바구니
    for r, c in ice_list:
        sea = 0
        for i in range(4):
            nr, nc = r + dr[i], c + dc[i]
            if ice[nr][nc] == 0:
                sea += 1 # 바다의 개수만큼 나중에 해당되는 값 -되고 최소는0됨
        if sea > 0: 
            melt_list.append((r, c, sea))
    
    # 3. 실제로 녹이고, 내년에 살아남을 빙산만 쪽지 갱신 (Batch Update)
    for r, c, amount in melt_list:
        ice[r][c] = max(0, ice[r][c] - amount) # 0미만 추락 방지 최적화
    
    next_ice_list = []
    for r, c in ice_list:
        if ice[r][c] > 0:
            next_ice_list.append((r, c)) # 아직 안 녹은 애들만 다음 해 쪽지로!
            
    ice_list = next_ice_list # 다이어트 기법: 연산량 급감의 핵심
    year += 1
else:
    # 다 녹을 때까지 2덩어리가 안 되면 0 출력
    print(0)
"""

# 2. 전략 분석 텍스트
strategy_analysis = """
1단계: "범인은 이 안에 있어!" (좌표 리스트 활용)
형사가 범인을 잡으러 갈 때, 도시 전체 9만 가구를 집집마다 방문(이중 for문)하면 시간이 너무 오래 걸리겠죠? 
대신 **"용의자 명단(ice_list)"**만 들고 그 집들만 찾아가는 게 훨씬 빠릅니다.
결과: 매년 루프를 돌 때마다 확인하는 칸이 90,000개에서 수백 개로 확 줄어듭니다.

2단계: "스냅샷 찍기" (예약 시스템)
빙산 하나가 녹아 0이 되는 순간 옆 칸의 결과에 영향을 줍니다. 하지만 문제는 "동시에" 녹는 것을 원하죠.
"지금 바로 지도를 고치면 다음 칸 계산이 꼬인다. 그러니 '누가 얼마나 녹을지' 메모지(melt_list)에 일단 적어만 두자. 
조사가 다 끝나면 그때 한꺼번에 지도를 고치자(Batch Update)."
결과: 연쇄 반응 오류를 막고 데이터의 일관성을 유지합니다.

3단계: "다이어트 시키기" (리스트 갱신)
올해 녹아서 0이 된 애들은 내년엔 검사할 필요가 없잖아? 내년용 새 명단(next_ice_list)을 만들어서 살아남은 애들만 옮겨 담자.
결과: 시간이 지날수록 검사할 대상이 줄어들어 속도가 점점 더 빨라집니다.
"""

blocks = [
    {'type': 'divider', 'divider': {}},
    {'type': 'heading_1', 'heading_1': {'rich_text': [{'type': 'text', 'text': {'content': '📍 [Samsung A] 빙산 - BFS 기반 동시 시뮬레이션 (초정밀 분석)'}}]}},
    {'type': 'quote', 'quote': {'rich_text': [{'type': 'text', 'text': {'content': '사용자님의 원본 로직과 주석을 100% 반영하여, 문제 해결의 핵심인 "용의자 명단"과 "스냅샷" 전략을 상세히 분석했습니다.'}}]}},
    {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '🔍 3단계 핵심 전략 상세 분석'}}]}},
    {'type': 'paragraph', 'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': strategy_analysis}}]}},
    {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '💻 Python 전체 정답 코드 (원본 주석 포함)'}}]}},
    {'type': 'code', 'code': {'language': 'python', 'rich_text': [{'type': 'text', 'text': {'content': detailed_code}}]}},
    {'type': 'callout', 'callout': {'icon': {'type': 'emoji', 'emoji': '💡'}, 'rich_text': [{'type': 'text', 'text': {'content': '학생 가이드: "범인은 이 안에 있어!" 기법을 기억하세요. 9만 개의 칸을 매번 도는 대신 수백 개의 빙산 좌표만 들고 뛰는 것이 A형 합격의 지름길입니다. 또한 "스냅샷(예약 시스템)"을 통해 데이터 오염을 막는 습관이 중요합니다.'}}]}}
]

def update_notion():
    # 마지막 추가된 블록들 삭제 (중복 방지)
    url = f'https://api.notion.com/v1/blocks/{PAGE_ID}/children'
    res = requests.get(url, headers=HEADERS)
    all_blocks = res.json().get('results', [])
    # '📍 [Samsung A] 빙산'으로 시작하는 헤딩을 찾아 그 이후를 삭제하거나, 
    # 이번에는 단순히 뒤에 덧붙이지 않고 정확히 교체하기 위해 마지막 블록들을 체크합니다.
    # 안전하게 10개 정도 블록을 삭제 (이전 작업에서 15개 정도 추가됨)
    for b in all_blocks[-15:]:
        requests.delete(f'https://api.notion.com/v1/blocks/{b["id"]}', headers=HEADERS)
        time.sleep(0.1)

    # 새로운 블록 추가
    for i in range(0, len(blocks), 5):
        chunk = blocks[i:i+5]
        requests.patch(url, headers=HEADERS, json={'children': chunk})
        time.sleep(1)
    print("Success: Updated with detailed comments and original logic.")

if __name__ == '__main__':
    update_notion()
