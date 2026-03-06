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

def append_advanced_dfs(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    
    blocks = [
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "💻 6. 가중치 & 누적 합 DFS (코딩 던전 스타일)"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "예산(K) 내에서 도달 가능한 노드를 찾는 패턴입니다. 누적값(`current_dist`)이 한계치를 넘는지 매 단계 검사합니다."}}]}},
        {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": """def dfs(node, current_dist, visited):
    visited[node] = current_dist # 현재까지의 가중치 기록

    for next_node, weight in graph[node]:
        # 아직 방문 안 했고, 예산(K) 내라면 탐색
        if visited[next_node] == -1:
            if current_dist + weight <= K:
                dfs(next_node, current_dist + weight, visited)
"""}}]}},
        
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "🔥 7. [심화] 가지치기(Pruning) 필살기"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "최적화 1: if current_sum >= min_ans: return # 이미 망한 경로는 버린다."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "최적화 2: 남은 칸을 다 합쳐도 현재 최고 기록을 못 깨면 return."}}]}},
        
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📝 8. 시험 직전 3분 체크리스트"}}]}},
        {"type": "to_do", "to_do": {"checked": False, "rich_text": [{"type": "text", "text": {"content": "DFS 인자로 depth와 sum을 넘겼는가?"}}]}},
        {"type": "to_do", "to_do": {"checked": False, "rich_text": [{"type": "text", "text": {"content": "visited 배열의 크기와 초기값이 적절한가?"}}]}},
        {"type": "to_do", "to_do": {"checked": False, "rich_text": [{"type": "text", "text": {"content": "재귀 호출 전후로 상태 복구(Backtracking)를 했는가?"}}]}},
        {"type": "to_do", "to_do": {"checked": False, "rich_text": [{"type": "text", "text": {"content": "4방 탐색(dr, dc) 시 인덱스 범위 체크를 했는가?"}}]}},
        
        {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "💯"}, "rich_text": [{"type": "text", "text": {"content": "이 페이지의 템플릿만 머릿속에 넣으면 어떤 DFS 문제도 10분 안에 설계 가능합니다. 화이팅!"}}]}}
    ]
    
    for chunk in chunk_blocks(blocks, size=3):
        res = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if res.status_code != 200:
            print(f"Failed to append chunk: {res.text}")
        else:
            print(f"Appended advanced chunk successfully.")
        time.sleep(1)

if __name__ == "__main__":
    page_id = "31beacc8-175a-813c-ba9b-c0ff8e8d5d98"
    append_advanced_dfs(page_id)
