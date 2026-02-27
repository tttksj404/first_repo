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

# 1. 원본 파일의 내용을 100% 보존하며, 추가적인 '강의식 상세 주석'을 코드 라인별로 보충한 버전
super_detailed_code = """'''
[빙산 문제 - BFS & 시뮬레이션 상세 전략]
1. BFS로 덩어리 개수 파악: 빙산이 1이상인 곳에서 시작하여 사방 탐색.
2. 녹이기 로직: 빙산의 동서남북 중 '0'(바다)의 개수만큼 높이가 줄어듦.
3. 주의사항: 녹는 과정은 '동시'에 진행되어야 함 (예약 시스템 필수).
4. 시간 복잡도 최적화: 9만 칸(300x300)을 매번 도는 대신, 빙산 좌표 리스트(ice_list)만 관리.
'''

from collections import deque
import sys
input = sys.stdin.readline

# N: 행의 개수, M: 열의 개수
N, M = map(int, input().split())
ice = []
ice_list = [] # <--- 이게 바로 그 '쪽지'입니다! (빙산이 있는 위치만 명단으로 관리)

for i in range(N):
    row = list(map(int, input().split()))
    ice.append(row)
    for j in range(M):
        if row[j] > 0:
            ice_list.append((i, j)) # 처음 빙산 위치만 딱 저장해둬요. (초기 명단 확보)

# 상하좌우 탐색을 위한 델타값
dr = [-1, 1, 0, 0]
dc = [0, 0, -1, 1]

# 1. 덩어리 세기 (이해하신 로직 그대로!)
def count_chunks(current_ice):
    visited = [[False] * M for _ in range(N)] # 매년 덩어리를 새로 셀 때마다 방문 기록 초기화
    chunks = 0
    for r, c in current_ice: # 9만 칸 전수 조사 대신, 주머니(명단)에 든 빙산 좌표만 확인! (초대박 최적화)
        if ice[r][c] > 0 and not visited[r][c]:
            # 아직 방문하지 않은 빙산을 발견하면 새로운 덩어리 BFS 시작
            q = deque([(r, c)])
            visited[r][c] = True
            while q:
                curr_r, curr_c = q.popleft()
                for i in range(4):
                    nr, nc = curr_r + dr[i], curr_c + dc[i]
                    # 범위를 벗어나지 않고(이미 바깥은 0이라 상관없음), 빙산이고, 방문 안 했다면 연결된 것!
                    if ice[nr][nc] > 0 and not visited[nr][nc]:
                        visited[nr][nc] = True
                        q.append((nr, nc))
            chunks += 1 # 한 번의 BFS(한 덩어리 탐색)가 끝나면 카운트 증가
    return chunks

year = 0
while ice_list: # 빙산 명단(ice_list)이 비어있지 않은 동안 (즉, 빙산이 다 녹을 때까지)
    # 1. 덩어리 개수 확인
    num = count_chunks(ice_list) 
    
    # 덩어리가 2개 이상이 되는 순간의 '년도'가 정답!
    if num >= 2:
        print(year)
        break
    
    # 2. 빙산 녹이기 (예약 시스템 - 스냅샷 기법)
    melt_list = [] # (행, 열, 녹을 양)을 저장할 임시 바구니
    for r, c in ice_list:
        sea = 0
        for i in range(4):
            nr, nc = r + dr[i], c + dc[i]
            if ice[nr][nc] == 0:
                sea += 1 # 주변 바다(0)의 개수만큼 나중에 해당되는 값 차감
        if sea > 0: 
            melt_list.append((r, c, sea)) # 지금 즉시 깎지 않고, '누가 얼마나 녹을지' 적어만 둠 (동시성 보장)
    
    # 3. 실제로 녹이고, 내년에 살아남을 빙산만 쪽지 갱신 (Batch Update)
    for r, c, amount in melt_list:
        # max(0, ...)를 써서 0미만으로 떨어지지 않게 방어 (삼성 A형 단골 최적화 기법)
        ice[r][c] = max(0, ice[r][c] - amount) 
    
    # 4. 다이어트 기법: 내년에도 살아있을 빙산만 추려서 새로운 명단 작성
    next_ice_list = []
    for r, c in ice_list:
        if ice[r][c] > 0:
            next_ice_list.append((r, c)) # 아직 안 녹은 애들만 다음 해 쪽지로 옮겨담음!
            
    ice_list = next_ice_list # 명단 교체 (연산 대상이 갈수록 줄어듦)
    year += 1
else:
    # 루프가 끝날 때까지 2덩어리가 안 되면 (즉, 한 번에 다 녹아버리거나 끝까지 1덩어리면) 0 출력
    print(0)


'''
[삼성 A형 합격을 위한 3단계 전략 핵심 요약]

1단계: "범인은 이 안에 있어!" (좌표 리스트 활용)
- 9만 칸(300x300)을 매번 돌지 마세요. 
- 빙산의 위치만 담은 ice_list를 관리하면 연산량이 1/100로 줄어듭니다.

2단계: "스냅샷 찍기" (예약 시스템)
- 빙산이 녹는 과정은 '동시'입니다. 
- 한 칸이 0이 되는 순간 옆 칸 연산에 영향을 주지 않도록, melt_list에 적어둔 뒤 한 번에 반영(Batch Update)하세요.

3단계: "다이어트 시키기" (리스트 갱신)
- 녹아서 사라진 빙산은 즉시 명단에서 제외하세요. 
- 년도가 지날수록 코드는 점점 더 빨라집니다.
'''
"""

blocks = [
    {'type': 'divider', 'divider': {}},
    {'type': 'heading_1', 'heading_1': {'rich_text': [{'type': 'text', 'text': {'content': '📍 [Samsung A] 빙산 - BFS 기반 동시 시뮬레이션 (초고농도 상세 주석)'}}]}},
    {'type': 'quote', 'quote': {'rich_text': [{'type': 'text', 'text': {'content': '사용자님의 원본 코드 주석을 한 글자도 빠짐없이 보존하고, 라인별 상세 해설을 추가하여 "공부하는 학생 시점"에서 완벽히 이해되도록 재구성했습니다.'}}]}},
    {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '💻 Python 전체 정답 코드 (라인별 밀착 해설)'}}]}},
    {'type': 'code', 'code': {'language': 'python', 'rich_text': [{'type': 'text', 'text': {'content': super_detailed_code}}]}},
    {'type': 'callout', 'callout': {'icon': {'type': 'emoji', 'emoji': '🏗️'}, 'rich_text': [{'type': 'text', 'text': {'content': '핵심 구현 포인트: ice_list(명단) -> melt_list(예약) -> next_ice_list(갱신)로 이어지는 3단계 루프가 이 문제의 정석입니다. BFS 덩어리 카운팅은 이 명단이 바뀔 때마다 수행하여 정확한 상태를 체크하세요.'}}]}}
]

def update_notion():
    url = f'https://api.notion.com/v1/blocks/{PAGE_ID}/children'
    res = requests.get(url, headers=HEADERS)
    all_blocks = res.json().get('results', [])
    
    # 방금 전 작업에서 추가된 📍 [Samsung A] 빙산 헤더를 찾아서 그 이후를 삭제
    target_start_index = -1
    for i, b in enumerate(all_blocks):
        if b['type'] == 'heading_1' and '빙산' in b['heading_1']['rich_text'][0]['plain_text']:
            target_start_index = i
            break
            
    if target_start_index != -1:
        print(f"Deleting blocks from index {target_start_index} to clean up...")
        for b in all_blocks[target_start_index:]:
            requests.delete(f'https://api.notion.com/v1/blocks/{b["id"]}', headers=HEADERS)
            time.sleep(0.1)

    # 새로운 고농도 블록 추가
    for i in range(0, len(blocks), 5):
        chunk = blocks[i:i+5]
        requests.patch(url, headers=HEADERS, json={'children': chunk})
        time.sleep(1)
    print("Success: Super detailed content updated with line-by-line comments.")

if __name__ == '__main__':
    update_notion()
