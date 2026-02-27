import requests
import json
import time

# 1. API Configuration

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
PAGE_ID = "2f0eacc8-175a-805c-85b2-dca59899d3d8"

# 사용자님의 실제 파일 내용 기반 데이터 (주석 추가)
user_data = [
    {
        "id": "2606",
        "title": "📍 [BJ 2606] 바이러스 - 사용자 원본 (그래프 연결)",
        "code": """'''
트리 형식의 트리 재귀 문제 
'''

n = int(input())
m = int(input())
# 1. 그래프 생성: n+1 크기로 설정하여 노드 번호를 인덱스로 직접 사용
graph = [[] for _ in range(n+1)] 
for pair in range(m):
    a,b = map(int,input().split())
    graph[a].append(b) # 양방향 연결
    graph[b].append(a)

# 2. 방문 처리 배열: DFS의 핵심 (한 번 간 곳은 다시 안 가기)
visited = [False]*(n+1) 
count=0

def dfs(start):
    global count
    visited[start]=True # 현재 노드 방문 표시

    for next_node in graph[start]: # 연결된 다음 노드들 탐색
        if not visited[next_node]: # 방문하지 않은 노드라면
            count+=1 # 감염된 컴퓨터 수 증가
            dfs(next_node) # 재귀 호출로 더 깊이 탐색
        
dfs(1) # 1번 컴퓨터부터 시작
print(count)"""
    },
    {
        "id": "2667",
        "title": "📍 [BJ 2667] 단지번호붙이기 - 사용자 원본 (델타 탐색)",
        "code": """'''
최단거리는 아님 -> 깊이 우선 탐색(DFS) 활용
'''
def dfs(a,b):
    global count    
    # 상하좌우 탐색을 위한 델타 리스트
    dr=[-1,1,0,0]
    dc=[0,0,-1,1]

    for idx in range(4):
        nr=a+dr[idx]
        nc=b+dc[idx]

        # 1. 격자 범위 내에 있고 2. 집(1)이 존재하며 3. 아직 방문하지 않은 경우
        if 0<=nr<N and 0<=nc<N and town[nr][nc]==1 and visited[nr][nc]==False:
            count+=1 # 단지 내 집 개수 추가
            visited[nr][nc]=True # 방문 처리
            dfs(nr,nc) # 재귀로 연결된 집 계속 찾기

storage=[]
N=int(input())
town = [list(map(int,input().strip())) for _ in range(N)]
visited = [[False]*N for _ in range(N)]

for i in range(N):
    for j in range(N):
        # 1을 찾고 + 아직 방문하지 않은 곳이어야 새로운 단지의 시작점이 됨
        if town[i][j]==1 and visited[i][j]==False:
            visited[i][j]=True # 시작점 방문 처리
            count=1 # 첫 번째 집 카운트
            dfs(i,j)
            storage.append(count) # 한 단지가 끝나면 리스트에 저장

storage.sort() # 문제 조건: 오름차순 정렬
print(len(storage)) # 총 단지 수
for ind in range(len(storage)):
    print(storage[ind])"""
    },
    {
        "id": "7569",
        "title": "📍 [BJ 7569] 토마토 - 사용자 원본 (3D BFS)",
        "code": """import sys
from collections import deque

# M:가로, N:세로, H:높이 (3차원 배열 구조)
M,N,H = map(int,sys.stdin.readline().split()) 
box = [] 
queue = deque()

# 1. 3차원 배열 입력 및 익은 토마토(1) 위치 큐에 삽입
for h in range(H):
    layer=[] 
    for n in range(N):
        row = list(map(int,sys.stdin.readline().split()))
        for m in range(M):
            if row[m]==1:
                # 멀티소스 BFS: 시작점이 여러 개일 때 모두 큐에 넣고 시작
                queue.append((h,n,m))
        layer.append(row)
    box.append(layer)

# 6방향 델타: 위, 아래, 상, 하, 좌, 우
dh=[1,-1,0,0,0,0]
dn=[0,0,-1,1,0,0]
dm=[0,0,0,0,-1,1]

while queue:
    h,n,m = queue.popleft() # 현재 위치 꺼내기

    for i in range(6):
        nh,nn,nm = h+dh[i], n+dn[i], m+dm[i]

        if 0<=nh<H and 0<=nn<N and 0<=nm<M:
            if box[nh][nn][nm]==0: # 안 익은 토마토 발견 시
                # 2. 거리(시간) 누적: 이전 값 + 1을 통해 소요 일수 계산
                box[nh][nn][nm]=box[h][n][m]+1 
                queue.append((nh,nn,nm)) 

ans =0
for layer in box:
    for row in layer:
        for meat in row:
            if meat ==0: # 전부 탐색했는데 0이 남았다면 모두 익지 못하는 상황
                print("-1")
                exit()
        ans= max(ans,max(row))

# 시작값이 1이었으므로 최종 결과에서 1을 빼야 정답 일수가 나옴
print(ans-1)"""
    }
]

def update_user_origin():
    print("🚀 사용자 원본 코드로 노션 정화 시작...")
    # 1. 페이지 블록 가져오기
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    res = requests.get(url, headers=HEADERS)
    blocks = res.json().get('results', [])
    
    # 2. 기존 문제 섹션을 찾아 원본 코드로 업데이트
    for data in user_data:
        for idx, block in enumerate(blocks):
            if block['type'] == 'heading_2':
                text = block['heading_2']['rich_text'][0]['plain_text']
                if data['id'] in text:
                    # 다음 블록이 코드 블록인지 확인 (보통 heading 바로 다음 혹은 몇 칸 뒤)
                    for next_idx in range(idx+1, min(idx+5, len(blocks))):
                        if blocks[next_idx]['type'] == 'code':
                            code_id = blocks[next_idx]['id']
                            requests.patch(f"https://api.notion.com/v1/blocks/{code_id}", headers=HEADERS, json={
                                "code": {"rich_text": [{"type": "text", "text": {"content": data['code']}}]}
                            })
                            print(f"✅ {data['id']} 원본 코드 및 주석 복구 완료")
                            break
                    break
    print("✨ 모든 원본 데이터 동기화 완료!")

if __name__ == "__main__":
    update_user_origin()
