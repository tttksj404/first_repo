import requests
import os
import json
import time
from pathlib import Path

# --- 인증 및 설정 ---
def get_token():
    paths = [Path(".env.notion"), Path("notion_automation/.env.notion")]
    for p in paths:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if "NOTION_TOKEN" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv("NOTION_TOKEN")

TOKEN = get_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PARENT_PAGE_ID = "303eacc8-175a-80a3-9154-f7a7acee7c80" # 코테 대비

def api_request(method, path, payload=None):
    url = f"https://api.notion.com/v1{path}"
    for attempt in range(1, 6):
        try:
            response = requests.request(method, url, headers=HEADERS, json=payload, timeout=30)
            if response.status_code == 429:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if attempt == 5: raise e
            time.sleep(2)

def create_page(title, parent_id):
    payload = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {"title": [{"text": {"content": title}}]}
        }
    }
    return api_request("POST", "/pages", payload)

def append_blocks(block_id, blocks):
    # Notion API has a limit of 100 blocks per request, but user wants 5-10 for stability
    for i in range(0, len(blocks), 10):
        chunk = blocks[i:i+10]
        api_request("PATCH", f"/blocks/{block_id}/children", {"children": chunk})
        time.sleep(0.5)

def rich_text(content, bold=False, color=None):
    res = {"type": "text", "text": {"content": content}}
    if bold or color:
        res["annotations"] = {}
        if bold: res["annotations"]["bold"] = True
        if color: res["annotations"]["color"] = color
    return res

def text_block(content, bold=False, color=None):
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [rich_text(content, bold, color)]}
    }

def heading_block(content, level=2):
    t = f"heading_{level}"
    return {
        "object": "block",
        "type": t,
        t: {"rich_text": [rich_text(content, bold=True)]}
    }

def callout_block(content, emoji="💡"):
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": emoji},
            "rich_text": [rich_text(content)]
        }
    }

def quote_block(content):
    return {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": [rich_text(content)]}
    }

def bullet_block(content, bold=False):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [rich_text(content, bold)]}
    }

def code_block(code, language="python"):
    # 2000 character limit for rich_text
    rich_texts = []
    for i in range(0, len(code), 1900):
        rich_texts.append({
            "type": "text",
            "text": {"content": code[i:i+1900]}
        })
    return {
        "object": "block",
        "type": "code",
        "code": {
            "language": language,
            "rich_text": rich_texts
        }
    }

def divider_block():
    return {"object": "block", "type": "divider", "divider": {}}

def todo_block(content):
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": [rich_text(content)]}
    }

# --- 데이터 준비 ---

problems = [
    {
        "title": "📍 [Samsung A] 풍선 팡 (재귀 & 브루트포스)",
        "quote": "삼성 A형의 단골 유형인 '순서가 중요한 완전 탐색' 문제입니다. 어떤 풍선을 먼저 터뜨리느냐에 따라 얻을 수 있는 점수가 달라지므로, Greedy보다는 모든 경우의 수를 따져보는 재귀(DFS)가 정답입니다.",
        "analysis": [
            ("현실 로직", [
                "풍선을 하나 고른다.",
                "그 풍선의 왼쪽과 오른쪽 이웃을 확인한다.",
                "왼쪽이 없으면 오른쪽 값만, 오른쪽이 없으면 왼쪽 값만, 둘 다 있으면 두 값의 곱을 점수로 얻는다.",
                "터뜨린 풍선은 사라지고, 남은 풍선들끼리 다시 이웃이 된다.",
                "마지막 하나가 남으면 그 풍선의 숫자 자체가 점수가 된다."
            ]),
            ("코딩 변환", [
                "get_max_score(list): 현재 남은 풍선 리스트를 인자로 받는 재귀 함수.",
                "for i in range(len(list)): 모든 풍선을 한 번씩 '먼저 터뜨려보는' 시뮬레이션.",
                "remains = list[:i] + list[i+1:]: 리스트 슬라이싱으로 터뜨린 풍선 제거.",
                "total = score + get_max_score(remains): 현재 얻은 점수와 남은 풍선들로 얻을 수 있는 최대 점수의 합."
            ])
        ],
        "checklist": [
            "풍선이 1개 남았을 때의 Base Case 처리",
            "인덱스 0과 N-1일 때의 예외 처리 (이웃이 하나뿐인 경우)",
            "리스트 슬라이싱을 통한 원본 보존 (백트래킹 효과)",
            "최대값 갱신 (max_result = max(max_result, total))"
        ],
        "file": "gitp/A형준비/ballonboom.py",
        "guide": "이 문제는 '순서'가 핵심입니다. N이 작다면(보통 10 이하) 모든 순서를 다 해보는 재귀가 가장 확실합니다. 리스트 슬라이싱을 활용하면 복잡한 인덱스 계산 없이도 터진 풍선을 쉽게 제외할 수 있습니다."
    },
    {
        "title": "📍 [Samsung A] 장기 포의 이동 (DFS & 백트래킹)",
        "quote": "장기판에서 '포'의 독특한 이동 규칙을 구현하는 문제입니다. 3번의 이동 제한 내에서 최대한 많은 쫄을 먹어야 하며, 한 번 먹은 쫄은 사라졌다가 다시 복구되는 '백트래킹'의 정석을 보여줍니다.",
        "analysis": [
            ("현실 로직", [
                "포는 상하좌우로 움직이지만, 반드시 '다리(다른 쫄)'가 하나 있어야 한다.",
                "다리를 넘기 전까지는 아무것도 할 수 없고, 다리를 하나 넘으면 그 뒤의 빈칸으로 가거나 첫 번째 적(쫄)을 먹을 수 있다.",
                "이미 먹은 쫄은 그 경로에서는 사라진 것으로 간주한다."
            ]),
            ("코딩 변환", [
                "dfs(r, c, count, eaten_set): 현재 포의 좌표, 이동 횟수, 먹은 쫄들의 좌표 집합.",
                "while 루프 1: 다리(값이 1인 칸)를 찾을 때까지 전진.",
                "while 루프 2: 다리를 찾은 후, 다시 전진하며 빈칸(0)이면 재귀 호출, 쫄(1)이면 먹고(eaten_set.add) 재귀 호출 후 중단.",
                "pan[nr][nc] = 0 -> dfs -> pan[nr][nc] = 1: 먹은 쫄의 상태 복구(백트래킹)."
            ])
        ],
        "checklist": [
            "포의 초기 위치(2)를 찾고 0으로 초기화",
            "3번 이동 제한(count == 3) 탈출 조건",
            "중복해서 먹는 쫄 방지 (eaten_set 사용)",
            "다리를 넘는 조건과 적을 먹는 조건의 구분"
        ],
        "file": "gitp/A형준비/jangki.py",
        "guide": "장기판 문제는 '장애물(다리)'을 어떻게 처리하느냐가 관건입니다. while 루프를 두 번 중첩하여 '다리 찾기'와 '이동/포획 가능 지점 찾기'를 분리하면 로직이 매우 깔끔해집니다. 먹은 쫄을 원복하는 백트래킹 포인트를 잊지 마세요!"
    },
    {
        "title": "📍 [Samsung A] 몬스터 소탕 (DFS & 순열 탐색)",
        "quote": "헌터가 몬스터를 잡고 고객에게 배달하는 문제입니다. 특정 몬스터를 잡아야만 해당 고객에게 갈 수 있다는 '선후 관계'가 핵심이며, 이를 만족하는 모든 방문 순서 중 최단 거리를 구해야 합니다.",
        "analysis": [
            ("현실 로직", [
                "몬스터(M)와 고객(C)은 짝이 정해져 있다 (1번 M -> 1번 C).",
                "처음엔 몬스터들만 잡으러 갈 수 있다.",
                "몬스터 하나를 잡는 순간, 그 몬스터의 짝인 고객이 새로운 방문 후보가 된다.",
                "모든 M과 C를 방문할 때까지 이 과정을 반복한다."
            ]),
            ("코딩 변환", [
                "locations: 모든 M, C의 좌표를 저장한 딕셔너리.",
                "candidates: 현재 방문 가능한 목적지 리스트 (처음엔 몬스터들만).",
                "dfs(pos, candidates, dist): 현재 위치, 후보지들, 누적 거리.",
                "candidates.pop(i) 후 방문 -> 만약 몬스터면 candidates.append(-target) (고객 추가) -> 재귀 -> candidates.pop() 및 candidates.insert(i, target) (복구)."
            ])
        ],
        "checklist": [
            "맨해튼 거리 계산 (abs(r1-r2) + abs(c1-c2))",
            "몬스터(양수)와 고객(음수)의 관계 설정",
            "min_dist를 이용한 가지치기 (Pruning)",
            "후보지 리스트의 동적 관리와 복구(백트래킹)"
        ],
        "file": "gitp/A형준비/monstercatcha.py",
        "guide": "이 문제는 '순열(Permutation)'을 생성하되, 특정 조건(M -> C)이 붙은 순열을 만드는 것과 같습니다. candidates 리스트를 재귀를 타고 내려가면서 유동적으로 관리하는 기법은 A형에서 매우 유용하게 쓰입니다."
    },
    {
        "title": "📍 [BFS] 2178 - 미로 탐색 (최단 거리의 정석)",
        "quote": "격자판 미로에서 (1, 1)부터 (N, M)까지의 최단 경로를 찾는 전형적인 BFS 문제입니다. '최단'이라는 키워드가 나오면 층위별 탐색이 보장되는 BFS를 먼저 떠올려야 합니다.",
        "analysis": [
            ("현실 로직", [
                "시작점에서 상하좌우로 한 칸씩 퍼져 나간다.",
                "이미 가본 길은 다시 가지 않는다 (최단 거리가 아니므로).",
                "도착지에 먼저 발을 들이는 놈의 발걸음 수가 바로 정답이다."
            ]),
            ("코딩 변환", [
                "deque([(0, 0)]): 큐를 이용한 너비 우선 탐색.",
                "dist[N][M]: 시작점으로부터의 거리를 저장하는 배열 (0이면 미방문).",
                "dist[nr][nc] = dist[r][c] + 1: 이전 칸의 거리 + 1로 갱신."
            ])
        ],
        "checklist": [
            "sys.stdin.readline과 strip()을 이용한 빠른 입력 처리",
            "상하좌우 델타 탐색 범위 체크 (0 <= nr < N and 0 <= nc < M)",
            "dist[0][0] = 1 초기값 설정",
            "목표 도달 시 즉시 return 하여 최적화"
        ],
        "file": "gitp/A형준비/bfs/2178.py",
        "guide": "미로 탐색은 BFS의 가장 기본적인 형태입니다. 큐(Queue)를 사용하여 가까운 곳부터 방문하기 때문에 처음 목표에 도달하는 경로가 무조건 최단 경로임을 보장합니다. 방문 여부와 거리를 dist 배열 하나로 관리하는 테크닉을 익히세요."
    }
]

def publish():
    for p in problems:
        print(f"🚀 '{p['title']}' 페이지 생성 중...")
        page = create_page(p['title'], PARENT_PAGE_ID)
        page_id = page['id']
        
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
        
        code = Path(p['file']).read_text(encoding="utf-8")
        blocks.append(code_block(code))
        
        blocks.append(divider_block())
        blocks.append(heading_block("💡 학생 가이드", level=2))
        blocks.append(callout_block(p['guide'], emoji="💡"))
        
        append_blocks(page_id, blocks)
        print(f"✅ '{p['title']}' 업로드 완료!")
        time.sleep(1)

if __name__ == "__main__":
    publish()
