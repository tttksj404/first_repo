import requests
import os
import json
import time
import sys
from pathlib import Path

# Fix encoding for Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# --- Authentication & Config ---
def get_token():
    paths = [Path(".env.notion"), Path("notion_automation/.env.notion"), Path("notion_key.txt"), Path("notion_automation/core/notion_key.txt")]
    for p in paths:
        if p.exists():
            content = p.read_text(encoding="utf-8").strip()
            if "NOTION_TOKEN=" in content:
                return content.split("NOTION_TOKEN=")[1].split("\n")[0].strip().strip('"').strip("'")
            return content
    return os.getenv("NOTION_TOKEN")

TOKEN = get_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PARENT_PAGE_ID = "303eacc8-175a-80a3-9154-f7a7acee7c80" # 코테 대비 (Problem Bank parent)

def api_request(method, path, payload=None):
    url = f"https://api.notion.com/v1{path}"
    for attempt in range(1, 6):
        try:
            response = requests.request(method, url, headers=HEADERS, json=payload, timeout=30)
            if response.status_code == 429:
                wait = 2 ** attempt
                print(f"Rate limited (429). Waiting {wait}s...")
                time.sleep(wait)
                continue
            if response.status_code >= 500:
                wait = 2 ** attempt
                print(f"Server error ({response.status_code}). Waiting {wait}s...")
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if attempt == 5: raise e
            time.sleep(2)

def search_page(query):
    payload = {"query": query, "filter": {"property": "object", "value": "page"}}
    data = api_request("POST", "/search", payload)
    return data.get("results", [])

def create_page(title, parent_id):
    payload = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {"title": [{"text": {"content": title}}]}
        }
    }
    return api_request("POST", "/pages", payload)

def append_blocks(block_id, blocks):
    # Rule: 5-10 blocks per chunk for stability
    for i in range(0, len(blocks), 8):
        chunk = blocks[i:i+8]
        api_request("PATCH", f"/blocks/{block_id}/children", {"children": chunk})
        time.sleep(0.5)

def rich_text(content, bold=False, color=None):
    # Rule: 2000 char limit for rich_text (use 1900 for safety)
    parts = []
    for i in range(0, len(content), 1900):
        part = {"type": "text", "text": {"content": content[i:i+1900]}}
        if bold or color:
            part["annotations"] = {}
            if bold: part["annotations"]["bold"] = True
            if color: part["annotations"]["color"] = color
        parts.append(part)
    return parts

def text_block(content, bold=False, color=None):
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text(content, bold, color)}
    }

def heading_block(content, level=2):
    t = f"heading_{level}"
    return {
        "object": "block",
        "type": t,
        t: {"rich_text": rich_text(content, bold=True)}
    }

def callout_block(content, emoji="💡"):
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": emoji},
            "rich_text": rich_text(content)
        }
    }

def quote_block(content):
    return {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": rich_text(content)}
    }

def bullet_block(content, bold=False):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(content, bold)}
    }

def code_block(code, language="python"):
    return {
        "object": "block",
        "type": "code",
        "code": {
            "language": language,
            "rich_text": rich_text(code)
        }
    }

def divider_block():
    return {"object": "block", "type": "divider", "divider": {}}

def todo_block(content):
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": rich_text(content)}
    }

# --- Data Preparation ---

problems_data = [
    {
        "search_query": "7576",
        "default_title": "📍 [BFS] 7576 - 토마토 (보관된 토마토들이 익는 최소 일수)",
        "quote": "격자판에서 여러 시작점(익은 토마토)으로부터 동시에 퍼져나가는 BFS의 전형적인 문제입니다. '모든 토마토가 익는 최소 시간'을 구해야 하므로, BFS의 레벨 탐색 특성을 활용하여 날짜를 계산하는 것이 핵심입니다.",
        "analysis": [
            ("현실 로직", [
                "익은 토마토(1)들이 있는 모든 칸에서 동시에 주변의 안 익은 토마토(0)들을 익게 만든다.",
                "하루가 지나면 익은 토마토 주변의 토마토들이 익는다.",
                "모든 토마토가 익을 때까지 며칠이 걸리는지 계산한다.",
                "만약 처음부터 다 익어있으면 0, 모두 익지 못하는 상황이면 -1을 출력한다."
            ]),
            ("코딩 변환", [
                "queue = deque([(r, c, 0), ...]): 처음에 익어있는 모든 토마토의 위치와 일수(0)를 큐에 다 넣고 시작한다 (Multi-source BFS).",
                "visited[r][c] = True: 방문 여부를 체크하여 중복 방문을 방지한다.",
                "while queue: 큐에서 꺼낸 토마토의 상하좌우를 살피며 0인 칸을 찾는다.",
                "grid[nr][nc] = 1 및 days = d + 1: 안 익은 토마토를 익음 처리하고 일수를 증가시켜 큐에 넣는다."
            ])
        ],
        "checklist": [
            "처음에 모든 익은 토마토(1)를 큐에 넣었는가? (동시 출발 보장)",
            "토마토가 하나도 없는 칸(-1)은 무시했는가?",
            "BFS 종료 후 여전히 안 익은 토마토(0)가 남아있는지 확인했는가?",
            "결과값이 0(이미 다 익음)인 경우와 -1(불가능)인 경우를 올바르게 처리했는가?"
        ],
        "file": "gitp/BFS/7576.py",
        "guide": "이 문제의 핵심은 '동시에 여러 곳에서 시작한다'는 점입니다. 큐에 처음부터 모든 시작점을 넣고 시작하면 자연스럽게 일차별로 확산되는 BFS가 구현됩니다. 마지막에 전체 판을 순회하며 0이 남아있는지 체크하는 루틴을 꼭 챙기세요."
    },
    {
        "search_query": "14940",
        "default_title": "📍 [BFS] 14940 - 쉬운 최단거리 (모든 지점에서의 목표지점까지 거리)",
        "quote": "특정 목표 지점(2)에서 시작하여 거꾸로 모든 지점까지의 최단 거리를 구하는 역발상 BFS 문제입니다. 갈 수 있는 땅(1) 중 도달할 수 없는 곳은 -1로 표시해야 한다는 조건에 주의해야 합니다.",
        "analysis": [
            ("현실 로직", [
                "목표 지점(2)을 시작점으로 잡고 BFS를 돌린다.",
                "상하좌우로 이동하며 거리를 1씩 늘려간다.",
                "원래 갈 수 없는 땅(0)은 거리 계산에서 제외하고 0으로 유지한다.",
                "원래 갈 수 있는 땅(1)인데 BFS가 도달하지 못했다면 -1로 표시한다."
            ]),
            ("코딩 변환", [
                "ans = [[-1] * M for _ in range(N)]: 전체를 -1로 초기화하면 도달하지 못한 곳을 따로 처리하기 쉽다.",
                "if grid[i][j] == 0: ans[i][j] = 0: 원래 못 가는 곳은 0으로 미리 세팅한다.",
                "queue = deque([(target_r, target_c)]): 목표 지점(2)의 위치를 찾아 큐에 넣고 ans[target_r][target_c] = 0으로 시작한다.",
                "ans[nr][nc] = ans[r][c] + 1: 다음 칸의 거리를 현재 칸 거리 + 1로 갱신한다."
            ])
        ],
        "checklist": [
            "목표 지점(2)의 좌표를 정확히 찾았는가?",
            "원래 못 가는 땅(0)에 대한 예외 처리를 했는가? (출력 시 0이어야 함)",
            "도달할 수 없는 땅(1)에 대해 -1이 출력되도록 했는가?",
            "방문 배열 대신 거리 배열(ans)의 초기값(-1)을 활용했는가?"
        ],
        "file": "gitp/BFS/14940.py",
        "guide": "보통 'A에서 B까지'를 구하지만, 이 문제는 '모든 칸에서 B까지'를 묻습니다. 이때는 B를 시작점으로 하여 한 번의 BFS만으로 모든 칸의 최단 거리를 구할 수 있습니다. 초기값을 -1로 설정하고 0인 칸을 미리 처리하는 것이 구현을 훨씬 단순하게 만듭니다."
    },
    {
        "search_query": "1260",
        "default_title": "📍 [Algorithm] 1260 - DFS와 BFS (그래프 탐색의 기초)",
        "quote": "하나의 그래프를 DFS와 BFS 두 가지 방식으로 탐색하며 그 차이를 명확히 이해할 수 있는 기초 문제입니다. 방문할 수 있는 정점이 여러 개인 경우 번호가 작은 것부터 방문해야 한다는 정렬 조건이 핵심입니다.",
        "analysis": [
            ("현실 로직", [
                "DFS(깊이 우선): 한 방향으로 갈 수 있는 데까지 깊게 들어갔다가 막히면 되돌아온다 (재귀/스택).",
                "BFS(너비 우선): 현재 위치에서 가까운 친구들부터 모두 만나고 다음 단계로 넘어간다 (큐).",
                "두 방식 모두 '방문 체크'가 중복 방문을 막는 핵심 장치이다."
            ]),
            ("코딩 변환", [
                "adj[u].sort(): 작은 번호부터 방문하기 위해 인접 리스트의 각 연결 정보를 오름차순으로 정렬한다.",
                "dfs(v): 방문 표시 후 출력, 연결된 정점 중 미방문 정점에 대해 재귀 호출.",
                "bfs(v): 큐에 시작점 넣고 방문 표시. 큐가 빌 때까지 꺼내서 연결된 미방문 정점들을 큐에 넣고 방문 표시."
            ])
        ],
        "checklist": [
            "인접 리스트(adj)를 정렬했는가?",
            "DFS와 BFS 각각에 대해 독립적인 방문 배열(visited)을 사용했는가?",
            "정점 번호가 1번부터 시작함에 주의하여 배열 크기를 N+1로 설정했는가?",
            "시작 정점 자체를 방문 표시하고 시작했는가?"
        ],
        "file": "gitp/DFS_백트래킹/1260DFS와 BFS.py",
        "guide": "그래프 탐색의 '두 기둥'을 동시에 연습하는 문제입니다. DFS는 재귀 구조를, BFS는 큐 구조를 사용한다는 차이점을 명확히 인지하세요. '작은 번호부터'라는 조건 때문에 정렬이 필수라는 점을 잊지 마세요."
    }
]

def publish():
    for p in problems_data:
        print(f"🔍 '{p['search_query']}' 페이지 검색 중...")
        results = search_page(p['search_query'])
        page_id = None
        if results:
            for res in results:
                # Try to find the best match
                title = "No Title"
                props = res.get('properties', {})
                for p_name in ['title', 'Name', '이름', '문제명']:
                    if p_name in props and props[p_name].get('title'):
                        title = props[p_name]['title'][0]['plain_text']
                        break
                if p['search_query'] in title:
                    page_id = res['id']
                    print(f"✅ 기존 페이지 발견: '{title}' (ID: {page_id})")
                    break
        
        if not page_id:
            print(f"🆕 새 페이지 생성 중: '{p['default_title']}'")
            new_page = create_page(p['default_title'], PARENT_PAGE_ID)
            page_id = new_page['id']
            print(f"✅ 새 페이지 생성 완료 (ID: {page_id})")

        # Prepare blocks
        blocks = []
        blocks.append(quote_block(p['quote']))
        blocks.append(divider_block())
        
        blocks.append(heading_block("🔍 상세 분석", level=2))
        for section_title, items in p['analysis']:
            blocks.append(text_block(f"📍 {section_title}", bold=True))
            for item in items:
                blocks.append(bullet_block(item))
        
        blocks.append(divider_block())
        blocks.append(heading_block("🏗️ 구현 체크리스트", level=2))
        for check in p['checklist']:
            blocks.append(todo_block(check))
            
        blocks.append(divider_block())
        blocks.append(heading_block("💻 전체 정답 코드", level=2))
        
        try:
            code = Path(p['file']).read_text(encoding="utf-8")
            blocks.append(code_block(code))
        except Exception as e:
            print(f"❌ 코드 파일 읽기 실패 ({p['file']}): {e}")
            blocks.append(text_block(f"❌ 코드 파일을 읽을 수 없습니다: {p['file']}", color="red"))
        
        blocks.append(divider_block())
        blocks.append(heading_block("💡 학생 가이드", level=2))
        blocks.append(callout_block(p['guide'], emoji="💡"))
        
        print(f"🚀 '{p['default_title']}' 내용 업로드 중...")
        append_blocks(page_id, blocks)
        print(f"✨ '{p['default_title']}' 업로드 완료!\n")
        time.sleep(1)

if __name__ == "__main__":
    publish()
