import requests
import json
import time
import os


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

# 🛠️ 정확한 블록 ID 매핑 (페이지 하단에 위치한 블록들)
target_blocks = {
    "1260": "314eacc8-175a-8126-b333-fdc1bfbff75c",
    "2178": "314eacc8-175a-8132-a9d7-c773772ff2d0",
    "2606": "314eacc8-175a-8192-b8ca-fdde096a9170",
    "2667": "314eacc8-175a-81c6-992b-c6f245c2c13d",
    "2644": "314eacc8-175a-81b8-aa64-d9aa2562cec2",
    "7569": "314eacc8-175a-81bf-98c1-efb5ac303825",
    "1697": "314eacc8-175a-815c-9a8f-f839d7779c17",
    "5014": "314eacc8-175a-8121-8764-c20d11646284",
    "2468": "314eacc8-175a-8108-be0b-f9ca1741f218",
    "1926": "314eacc8-175a-8120-afa5-cf0309789b07"
}

# 사용자님이 채팅창에 주신 1260, 2178 코드
code_1260 = """import sys
from collections import deque

# 재귀 한도 설정 (DFS를 위해)
sys.setrecursionlimit(10**6)
input = sys.stdin.readline

# N: 정점 개수, M: 간선 개수, V: 시작 정점
n, m, v = map(int, input().split())

# 인접 리스트로 그래프 구현
graph = [[] for _ in range(n + 1)] #[]를 다 찍어주기 

for _ in range(m):
    a, b = map(int, input().split())
    graph[a].append(b) #a의 인접값인 b 넣어주고 
    graph[b].append(a) #b의 인접값으로 당연히 a 넣어줌 이게 [a] [b...] / [b] [a.....]이런형식 

# "번호가 작은 것부터 방문"하기 위해 정렬 [][]순서에서 앞뒤 순서 정렬 ex)1 4 / 1 3 / 1 2  이면 [1] [4,3,2]나와서 이걸 sort로 [1] [2,3,4]
for i in range(1, n + 1):
    graph[i].sort()

# DFS 구현 (재귀)
def dfs(node, visited):
    visited[node] = True #재방문 막고자 하기 위해 메커니즘 시작전 제약조건인 true 걸어두고 시작 
    #그냥 visited는 true false로 이뤄져서 인덱스 찾고 그 값은 true, false임 / bfs에서 visited를 정의했는데 만약 dfs에서 정의하면 재귀로 계속 초기화 되기에
    print(node, end=' ')
    for next_node in graph[node]:
        if not visited[next_node]:
            dfs(next_node, visited)

# BFS 구현 (큐) #재귀 필요 x 이미 처음부터 제대로 넓게 탐색한다고 생각하기에 
def bfs(start):
    visited = [False] * (n + 1) #(n+1)의 이유 인덱스 번호 맞추려고 [false]라서 애초에 리스트 인덱스 생각 
    queue = deque([start]) #시작점 찍어주기 
    visited[start] = True #시작점은 방문 이력 남김 
    
    while queue:
        node = queue.popleft() #큐에서 왼쪽꺼 즉 처음 시작값은 버려야 초기화됨 그리고 방문했던 값도 버리고 그걸 프린트해야 방문 했다고 출력가능 
        print(node, end=' ')
        for next_node in graph[node]: #그래프에 담긴 값 즉 전체 범위내에서 다음 노드 탐색 
            if not visited[next_node]: #방문이력에 해당 다음 방문할 노드 없다면
                visited[next_node] = True #방문할꺼니까 방문이력 남기기 
                queue.append(next_node) #그리고 그 노드는 큐에 담기 

# 결과 출력
visited_dfs = [False] * (n + 1)
dfs(v, visited_dfs) #dfs탐색을 시작할 정점의 번호 v 
print() # 줄바꿈
bfs(v) #bfs탐색을 시작할 정점의 번호 v"""

code_2178 = """from collections import deque 
import sys
input= sys.stdin.readline


def bfs():
    N,M = map(int,input().split())
    maze = [list(map(int,input().strip())) for _ in range(N)]

    dist = [[0]*M for _ in range(N)]
    dr= [-1,1,0,0]
    dc=[0,0,-1,1]

    queue = deque([(0,0)]) #queue를 써야지 시작점으로 부터 근거리있는 것부터 first in first out으로 처리하기에

    #만약 스택이면 가장 나중 last in first out이기에 4방 탐색에서 한쪽에 있는 부분만 먼저 갔다가 계속 그렇게 나아가서 
    #목표 찍고 돌아오게된다 
    dist[0][0]=1

    while queue:
        r,c=queue.popleft() 

        if r==N-1 and c==M-1: #bfs로 목표를 찍고 돌아올 경우
            return dist[r][c]
        
        for a in range(4):
            nr = r+dr[a]
            nc= c+dc[a]
            #문제의 조건 부분은 델타탐색의 조건에서 추가로 더 해주면된다
            if 0<=nr<N and 0<=nc<M and maze[nr][nc]==1 and dist[nr][nc]==0:
                dist[nr][nc]=dist[r][c]+1
                queue.append((nr,nc))
    return -1 #실제로는 작동하지 않지만 길이없는 예외상황을 설명하기 위한 안전장치임 

print(bfs())"""

# 로컬 파일 경로 매칭
file_map = {
    "2606": "gitp/DFS_백트래킹/2606dfs그래프노드연결.py",
    "2667": "gitp/DFS_백트래킹/2667dfs백트래킹 핵심.py",
    "2644": "gitp/DFS_백트래킹/2644dfs에서의 실패하고 돌아올때 중복개수 방지.py",
    "7569": "gitp/BFS/75693차원 bfs 큐이용.py",
    "1697": "gitp/BFS/1697그래프 시간초과나서 안쓰는bfs.py",
    "5014": "gitp/BFS/5014그래프 안쓰는 bfs.py",
    "2468": "gitp/BFS/2468델타응용 bfs.py"
}

def update():
    for pid, block_id in target_blocks.items():
        code_text = ""
        if pid == "1260": code_text = code_1260
        elif pid == "2178": code_text = code_2178
        elif pid in file_map:
            if os.path.exists(file_map[pid]):
                with open(file_map[pid], 'r', encoding='utf-8') as f:
                    code_text = f.read()
        
        if code_text:
            url = f"https://api.notion.com/v1/blocks/{block_id}"
            res = requests.patch(url, headers=HEADERS, json={
                "code": {"rich_text": [{"type": "text", "text": {"content": code_text}}]}
            })
            if res.status_code == 200:
                print(f"✅ SUCCESS: Updated Block for BJ {pid}")
            else:
                print(f"❌ FAILED: BJ {pid} - {res.text}")
            time.sleep(0.5)

if __name__ == "__main__":
    update()
