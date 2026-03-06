import requests
import json
import time
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def chunk_blocks(blocks, size=5):
    for i in range(0, len(blocks), size):
        yield blocks[i:i+size]

def create_dfs_master_page(parent_id):
    url = "https://api.notion.com/v1/pages"
    
    # 1. Create the page first
    new_page_payload = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {
                "title": [{"text": {"content": "📍 [Samsung A] DFS & 백트래킹 극한의 정복 (IM Master Style)"}}]
            }
        }
    }
    
    res = requests.post(url, headers=HEADERS, json=new_page_payload)
    if res.status_code != 200:
        print(f"Failed to create page: {res.text}")
        return
    
    page_id = res.json()["id"]
    print(f"Created page: {page_id}")
    
    # 2. Define the content blocks (Massive detail!)
    blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. DFS의 본질: 현실 로직 vs 코딩 로직"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "DFS는 '갈 수 있는 데까지 가본다'는 철학입니다. A형에서는 단순히 탐색만 하는 것이 아니라, '갔다가 돌아오는(백트래킹)' 과정에서의 상태 복구가 핵심입니다."}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🏗️ 2. 구현 체크리스트 (5계명)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "1. 파라미터 설계: (현재 노드, 깊이, 누적값)은 필수!"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "2. 종료 조건(Base Case): depth == M 또는 목표 도달 시 반드시 return."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "3. 가지치기(Pruning): 이미 최솟값을 넘었다면 더 볼 필요 없다!"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "4. 방문 처리와 해제: v[i]=True -> dfs() -> v[i]=False (세트 메뉴)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "5. 방향 탐색: dr, dc 델타 배열로 4방/8방 탐색 자동화."}}]}},
        
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "💻 3. A형 필수 템플릿: 순열 & 조합 백트래킹"}}]}},
        {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": """# N개 중 M개를 뽑는 순열 (중복 X)
def dfs(depth):
    if depth == M: # 종료 조건
        print(*path)
        return

    for i in range(1, N + 1):
        if not visited[i]:
            visited[i] = True # 상태 변경
            path.append(i)
            
            dfs(depth + 1) # 다음 단계 재귀 호출
            
            path.pop() # 상태 복구 (Backtracking)
            visited[i] = False
"""}}]}},
        
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "💻 4. A형 필수 템플릿: 격자(Grid) 탐색"}}]}},
        {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": """# 맵에서 연결된 구역 찾기 (Flood Fill)
def dfs(r, c):
    visited[r][c] = True
    
    for dr, dc in [(-1,0), (1,0), (0,-1), (0,1)]: # 상하좌우
        nr, nc = r + dr, c + dc
        if 0 <= nr < N and 0 <= nc < N: # 경계 검사
            if board[nr][nc] == 1 and not visited[nr][nc]:
                dfs(nr, nc)
"""}}]}},
        
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "💡 5. 삼성 A형 실전 필살기"}}]}},
        {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "🚀"}, "rich_text": [{"type": "text", "text": {"content": "재귀 깊이 설정: sys.setrecursionlimit(10**6)는 습관적으로 적으세요. 안 적으면 1000번 이상 호출 시 런타임 에러 납니다!"}}]}},
        {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "🛠️"}, "rich_text": [{"type": "text", "text": {"content": "디버깅 팁: print(f'{depth*\"  \"} IN: {node}') 를 함수 시작에 넣으면 트리 구조를 시각적으로 볼 수 있습니다."}}]}}
    ]
    
    # 3. Append blocks in chunks (Double Chunking Protocol)
    append_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    for chunk in chunk_blocks(blocks, size=3):
        res = requests.patch(append_url, headers=HEADERS, json={"children": chunk})
        if res.status_code != 200:
            print(f"Failed to append chunk: {res.text}")
        else:
            print(f"Appended chunk successfully.")
        time.sleep(1) # Exponential backoff/Rate limit handling
    
    print(f"\n✅ All set! DFS Mastery page is ready at: https://notion.so/{page_id.replace('-', '')}")

if __name__ == "__main__":
    # Using the 'DFS/BFS' page ID (Confirmed visible to integration)
    target_id = "2f0eacc8-175a-805c-85b2-dca59899d3d8"
    create_dfs_master_page(target_id)
