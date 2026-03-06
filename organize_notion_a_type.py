import requests
import time
import os
from pathlib import Path
from notion_automation.core.notion_env import get_notion_token

# --- 인증 및 설정 ---
TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PARENT_PAGE_ID = "303eacc8-175a-80a3-9154-f7a7acee7c80" # 코딩 대비

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
        "file": "gitp/완전탐색_시뮬레이션/ballonboom.py",
        "quote": "어떤 풍선을 먼저 터뜨리느냐에 따라 얻는 점수가 달라지는 '순서 결정' 문제입니다. 풍선의 개수(N)가 적다면 모든 순서를 따져보는 재귀가 가장 확실합니다.",
        "analysis": [
            ("현실 로직", [
                "N개의 풍선 중 하나를 선택해 터뜨린다.",
                "터뜨린 풍선의 양옆 숫자를 확인하여 점수를 계산한다.",
                "터뜨린 풍선은 리스트에서 제거하고, 남은 풍선들로 다시 게임을 진행한다.",
                "마지막 하나가 남을 때까지 반복하여 최대 점수를 찾는다."
            ]),
            ("코딩 변환", [
                "get_max_score(list): 현재 남은 풍선 리스트를 넘겨주는 재귀 함수.",
                "remains = current[:i] + current[i+1:]: 슬라이싱을 통해 터진 풍선을 제외한 새 리스트 생성.",
                "score = current[i-1] * current[i+1]: 양옆 풍선의 곱 (인덱스 0, N-1 예외 처리 필수)."
            ])
        ],
        "checklist": [
            "Base Case: 풍선이 1개 남았을 때의 점수 반환",
            "인덱스 범위 체크: 맨 왼쪽(0)과 맨 오른쪽(len-1)일 때의 점수 계산 로직 분기",
            "최대값 갱신: 각 경로에서 얻은 total 점수 중 최댓값 유지"
        ],
        "guide": "이 문제는 '순열'을 직접 구현하지 않고도 재귀 함수의 인자로 리스트를 넘기며 자연스럽게 모든 경우의 수를 탐색할 수 있습니다. N이 10 이하일 때 매우 유용한 기법입니다."
    },
    {
        "title": "📍 [Samsung A] 장기 포의 이동 (DFS & 백트래킹)",
        "file": "gitp/BFS/jangki.py",
        "quote": "장기판의 '포'가 다리를 넘고 쫄을 먹는 독특한 이동 규칙을 구현합니다. 3번의 기회 내에서 최대한 많은 쫄을 먹기 위한 백트래킹의 정석입니다.",
        "analysis": [
            ("현실 로직", [
                "포는 반드시 '다리'가 하나 있어야만 넘을 수 있다.",
                "다리를 넘은 뒤에는 빈칸에 착지하거나 첫 번째 쫄을 먹을 수 있다.",
                "한 번의 경로에서 먹은 쫄은 사라졌다가, 다른 경로를 탐색할 때는 다시 나타나야 한다."
            ]),
            ("코딩 변환", [
                "dfs(cur_pos, count): 현재 위치와 이동 횟수.",
                "while 루프: 한 방향으로 쭉 전진하며 다리 찾기 -> 다리 찾은 후 다시 while로 착지/포획 지점 찾기.",
                "matrix[ny][nx] = 0 -> dfs -> matrix[ny][nx] = 1: 쫄을 먹고 원복하는 백트래킹 로직."
            ])
        ],
        "checklist": [
            "포의 초기 위치(2)를 0으로 바꾸고 시작",
            "이동 횟수 3번 제한 (n == 3) 탈출 조건",
            "중복 포획 방지: checked 배열이나 set을 사용하여 먹은 쫄의 위치 기록",
            "다리 바로 다음 칸부터만 착지 가능하다는 점 유의"
        ],
        "guide": "다리를 찾는 '첫 번째 구간'과 이동 가능한 '두 번째 구간'을 while 문으로 나누어 처리하는 것이 핵심입니다. 복잡한 델타 탐색 속에서도 백트래킹 포인트를 명확히 잡으세요."
    },
    {
        "title": "📍 [Samsung A] 몬스터 소탕 (DFS & 순열)",
        "file": "gitp/DFS_백트래킹/monstercatcha.py",
        "quote": "몬스터를 잡아야 고객에게 갈 수 있다는 '선후 관계'가 포함된 순열 문제입니다. 후보지 리스트를 동적으로 관리하는 테크닉이 요구됩니다.",
        "analysis": [
            ("현실 로직", [
                "헌터는 몬스터(M)를 먼저 잡아야만 해당 고객(C)에게 배달할 수 있다.",
                "현재 방문할 수 있는 곳(후보지)은 '아직 안 잡은 몬스터'와 '이미 잡은 몬스터의 고객'들이다.",
                "모든 장소를 방문하는 최소 거리를 구한다."
            ]),
            ("코딩 변환", [
                "candidates.pop(i): 방문한 곳을 후보에서 제거.",
                "if target > 0: 몬스터라면 candidates.append(-target)으로 해당 고객을 후보에 추가.",
                "candidates.insert(i, target): 재귀에서 돌아온 후 후보 리스트 복구."
            ])
        ],
        "checklist": [
            "맨해튼 거리 함수 구현 (abs(r1-r2) + abs(c1-c2))",
            "몬스터(양수)와 고객(음수)의 데이터 매칭",
            "min_dist를 활용한 가지치기 (현재 거리가 이미 최솟값보다 크면 중단)",
            "재귀 호출 전후의 리스트 상태 복구(Backtracking) 철저"
        ],
        "guide": "고정된 순열이 아니라, 방문할 때마다 다음 후보가 늘어나거나 줄어드는 '동적 순열' 문제입니다. 리스트의 pop, append, insert를 적절히 활용하여 상태를 관리하세요."
    },
    {
        "title": "📍 [Samsung A] 사과 먹기 (시뮬레이션 & 방향 전환)",
        "file": "gitp/완전탐색_시뮬레이션/eatingapple.py",
        "quote": "달팽이처럼 우회전만 하며 사과를 순서대로 먹어야 합니다. 현재 방향과 목표 위치 사이의 '사분면 관계'를 통해 우회전 횟수를 결정하는 것이 포인트입니다.",
        "analysis": [
            ("현실 로직", [
                "1번 사과부터 순서대로 찾아가야 한다.",
                "갈 수 있는 방법은 오직 전진과 우회전뿐이다.",
                "목표 사과가 현재 내 위치 기준으로 어느 방향(사분면)에 있느냐에 따라 우회전 횟수가 정해진다."
            ]),
            ("코딩 변환", [
                "target 딕셔너리: 각 사과 번호별 좌표 저장.",
                "turn_matrix: [현재방향][목표사분면]에 따른 회전 횟수 미리 정의.",
                "current_dir = (current_dir + turns) % 4: 회전 후 방향 갱신."
            ])
        ],
        "checklist": [
            "사과가 없는 칸(0)과 있는 칸(1~M) 구분",
            "좌표계 기준 사분면 판단 로직 (현재 위치 r, c 기준)",
            "시작 방향(우측, 0)과 초기 위치(0, 0) 설정",
            "0-1 BFS로도 풀 수 있으나, 사분면 규칙을 찾으면 더 빠름"
        ],
        "guide": "삼성 시뮬레이션에서는 '방향' 관리가 절반입니다. 우회전 횟수를 하드코딩하기보다 행렬(turn_matrix)로 관리하면 실수를 획기적으로 줄일 수 있습니다."
    },
    {
        "title": "📍 [Samsung A] 코딩 던전 (DFS & 예산 관리)",
        "file": "gitp/DFS_백트래킹/codingdaungeon.py",
        "quote": "한정된 골드 내에서 도달 가능한 모든 던전을 찾는 그래프 탐색 문제입니다. 누적 비용을 체크하며 방문하는 DFS의 기본을 보여줍니다.",
        "analysis": [
            ("현실 로직", [
                "출발지(0번)에서 연결된 던전들을 탐색한다.",
                "던전 사이의 길은 통행료가 있으며, 총 비용이 예산(K)을 넘으면 안 된다.",
                "도달한 적 있는 모든 던전 번호를 기록한다."
            ]),
            ("코딩 변환", [
                "graph: 인접 리스트로 연결 상태와 가중치 저장.",
                "if current_dist + weight <= K: 다음 노드로 가기 전 예산 체크.",
                "storage.append(node) + set(storage): 도달 가능한 던전 중복 제거."
            ])
        ],
        "checklist": [
            "양방향 그래프 여부 확인",
            "visited 배열을 -1 등으로 초기화하여 방문 여부와 최소 비용 동시 관리 가능",
            "결과 출력 시 정렬 및 중복 제거 요구사항 확인",
            "출발지(0번)는 결과에서 제외하는 조건 확인"
        ],
        "guide": "단순 방문 여부만 따지는 게 아니라 '누적 가중치'가 한도를 넘지 않아야 합니다. DFS 인자에 현재까지의 비용을 계속 실어 보내는 연습을 하세요."
    },
    {
        "title": "📍 [Topological Sort] 14567 - 위상 정렬 (선수 과목)",
        "file": "gitp/BFS/14567위상정렬.py",
        "quote": "순서가 정해진 작업들을 차례대로 수행하는 위상 정렬 문제입니다. 진입 차수(Indegree)가 0인 노드부터 큐에 넣는 것이 핵심입니다.",
        "analysis": [
            ("현실 로직", [
                "먼저 들어야 하는 과목(선수 과목)이 없는 것부터 공부한다.",
                "공부를 끝낸 과목은 목록에서 지우고, 그 과목 때문에 못 듣고 있던 다음 과목들의 '대기 수'를 줄인다.",
                "이제 대기 수가 0이 된 과목들을 다시 공부한다."
            ]),
            ("코딩 변환", [
                "indegree = [0] * (N+1): 각 노드로 들어오는 간선 개수.",
                "queue: indegree가 0인 노드들을 담는 통.",
                "semester[next] = max(semester[next], semester[curr] + 1): 이수 학기 갱신."
            ])
        ],
        "checklist": [
            "그래프 구성 시 단방향(a -> b)으로 설정",
            "초기 진입 차수가 0인 모든 노드를 큐에 넣고 시작",
            "여러 선수 과목 중 '가장 나중에 끝나는' 학기를 기준으로 갱신"
        ],
        "guide": "위상 정렬은 '사이클이 없는 유향 그래프(DAG)'에서만 가능합니다. 큐에서 뺀 노드와 연결된 노드들의 진입 차수를 하나씩 줄여가는 로직을 기계적으로 익히세요."
    },
    {
        "title": "📍 [Dijkstra] 1753 - 최단 경로",
        "file": "gitp/BFS/1753다익스트라.py",
        "quote": "가중치가 있는 그래프에서 특정 시작점으로부터 모든 정점까지의 최단 거리를 구합니다. 우선순위 큐(Heapq)를 이용한 그리디적 접근이 핵심입니다.",
        "analysis": [
            ("현실 로직", [
                "시작점의 거리는 0, 나머지는 무한대로 설정한다.",
                "가장 가까운(거리가 짧은) 정점을 하나 골라 방문한다.",
                "그 정점을 거쳐서 다른 정점으로 가는 게 기존에 알던 거리보다 짧다면 정보를 갱신한다.",
                "모든 정점을 방문할 때까지 반복한다."
            ]),
            ("코딩 변환", [
                "dist = [INF] * (V+1): 최단 거리 테이블.",
                "heapq.heappush(pq, (0, start)): (거리, 노드) 순으로 힙에 저장.",
                "if dist[now] < distance: continue: 이미 처리된 노드라면 건너뛰기(최적화)."
            ])
        ],
        "checklist": [
            "INF 값을 충분히 크게 설정 (1e8 이상)",
            "우선순위 큐에 넣을 때 (거리, 노드) 순서 주의 (거리 기준 정렬)",
            "방문한 노드의 거리 갱신 시 `dist[next] = new_dist` 후 힙에 삽입"
        ],
        "guide": "다익스트라는 음의 가중치가 없을 때만 사용 가능합니다. 매 순간 '가장 짧은 거리'를 확정 지으며 나아가는 방식이므로 BFS와 힙큐가 결합된 형태임을 이해하세요."
    },
    {
        "title": "📍 [BFS] 3184 - 양과 늑대 (영역 탐색)",
        "file": "gitp/BFS/3184bfs정석여러변수.py",
        "quote": "울타리로 나뉜 각 영역을 BFS로 탐색하며 양과 늑대의 수를 비교합니다. 영역별 독립적인 카운팅이 필요한 전형적인 격자 탐색 문제입니다.",
        "analysis": [
            ("현실 로직", [
                "장기판(마당)을 하나씩 확인하며 아직 안 가본 빈칸이나 동물을 찾는다.",
                "그 지점부터 울타리(#)에 막히기 전까지 연결된 모든 칸을 샅샅이 뒤진다.",
                "그 구역 안에 있는 양과 늑대의 수를 세서, 양이 더 많으면 양만 살리고 아니면 늑대만 살린다."
            ]),
            ("코딩 변환", [
                "visited[R][C]: 방문 여부 체크 배열.",
                "while queue: 사방 탐색을 하며 같은 영역인 'o', 'v', '.'을 큐에 추가.",
                "sheep_total, wolf_total: 각 영역의 결과를 합산할 전역 변수."
            ])
        ],
        "checklist": [
            "BFS 시작 지점이 '양'이나 '늑대'인 경우 초기 카운트(1) 설정",
            "울타리(#)는 큐에 넣지 않고 방문 처리도 하지 않음",
            "전체 격자를 순회하며 '방문하지 않은' 칸에 대해서만 BFS 실행"
        ],
        "guide": "영역을 나누는 BFS에서는 '언제 BFS를 시작할 것인가'와 '영역 내부에서 무엇을 할 것인가'를 분리해서 생각하세요. `o`와 `v`를 만날 때마다 카운트만 올리고 BFS 종료 후 비교하면 끝입니다."
    },
    {
        "title": "📍 [Parametric Search] 2805 - 나무 자르기",
        "file": "gitp/그리디/2805이진탐색.py",
        "quote": "적어도 M미터의 나무를 가져가기 위한 절단기 높이의 최댓값을 구합니다. '최댓값을 찾아라'를 '높이 H일 때 M미터 이상 가능한가?'라는 결정 문제로 바꾸는 이진 탐색입니다.",
        "analysis": [
            ("현실 로직", [
                "절단기 높이를 0부터 가장 높은 나무 높이 사이에서 정한다.",
                "특정 높이로 잘랐을 때 나오는 나무들의 합을 구한다.",
                "나무가 너무 많으면 높이를 높이고, 부족하면 높이를 낮춘다.",
                "이 과정을 반복하며 M미터를 딱 맞추거나 조금 더 많이 가져가는 최적의 높이를 찾는다."
            ]),
            ("코딩 변환", [
                "left, right = 0, max(woods): 탐색 범위 설정.",
                "total = sum(max(wood - mid, 0)): mid 높이로 잘랐을 때 얻는 나무 합.",
                "if total < M: right = mid / else: left = mid + 1: 이진 탐색 로직."
            ])
        ],
        "checklist": [
            "나무 높이의 최댓값이 매우 크므로 (20억) 반드시 O(N log H) 수준의 이진 탐색 필요",
            "total 계산 시 음수가 되지 않도록 `max(0, wood - mid)` 사용",
            "Upper Bound / Lower Bound 조건에 따른 결과값(`left-1` 등) 미세 조정"
        ],
        "guide": "최적화 문제(최대/최소 구하기)를 결정 문제(Yes/No)로 바꾸는 파라메트릭 서치는 삼성 A형과 코테의 단골입니다. mid 값을 정하고, 그 mid가 정답이 될 수 있는지 함수를 통해 검증하세요."
    },
    {
        "title": "📍 [BFS] 2178 - 미로 탐색 (최단 경로)",
        "file": "gitp/BFS/2178미로탐색_기본.py",
        "quote": "(1, 1)에서 (N, M)까지 가는 최소 칸 수를 구합니다. 가중치가 1인 그래프에서의 최단 거리는 BFS가 가장 빠르고 정확합니다.",
        "analysis": [
            ("현실 로직", [
                "출발점에서 인접한 칸들을 먼저 다 가본다.",
                "각 칸에 갈 때마다 '여기까지 몇 칸 왔는지'를 적어둔다.",
                "가장 먼저 도착점에 닿는 경로가 가장 빠른 길이다."
            ]),
            ("코딩 변환", [
                "dist[nr][nc] = dist[r][c] + 1: 이전 칸의 거리 정보를 누적.",
                "if r == N-1 and c == M-1: return dist[r][c]: 도착 즉시 종료.",
                "visited 대신 dist 배열의 0값 여부로 중복 방문 체크."
            ])
        ],
        "checklist": [
            "입력값이 붙어있는 경우 `input().strip()`으로 받아 리스트화",
            "시작 위치(0,0)의 거리 초기값을 1로 설정 (문제 조건에 따라)",
            "큐(Queue)를 사용해야만 최단 거리가 보장됨 (Stack 사용 시 DFS가 됨)"
        ],
        "guide": "BFS는 층위(Level)별 탐색입니다. 거리 1인 곳 다 가고, 거리 2인 곳 다 가는 식이므로 도착점에 먼저 도달하는 놈이 무조건 1등입니다."
    },
    {
        "title": "📍 [Backtracking] 1759 - 암호 만들기",
        "file": "gitp/DFS_백트래킹/1759암호생성_백트래킹.py",
        "quote": "주어진 문자들로 조건을 만족하는 암호를 생성합니다. 사전순 출력을 위해 정렬 후 조합(Combination)을 뽑는 백트래킹 문제입니다.",
        "analysis": [
            ("현실 로직", [
                "사용 가능한 알파벳들을 사전순으로 정렬한다.",
                "L개의 문자를 중복 없이 뽑아 암호를 만든다 (뽑을 때는 사전순 유지).",
                "만들어진 암호가 모음 1개 이상, 자음 2개 이상을 포함하는지 확인한다."
            ]),
            ("코딩 변환", [
                "chars.sort(): 사전순 정렬.",
                "solve(start, path): 현재 인덱스 이후의 문자만 선택하여 조합 생성.",
                "is_valid(password): 모음/자음 개수 카운트 및 조건 체크."
            ])
        ],
        "checklist": [
            "사전순 출력을 위해 입력 문자를 먼저 정렬했는지 확인",
            "조합(Combination)이므로 재귀 호출 시 `i + 1`을 인자로 전달",
            "모음(`aeiou`)과 자음의 개수 조건(1개 이상, 2개 이상) 정확히 구현"
        ],
        "guide": "백트래킹에서 '순서'가 상관없고 '조합'만 뽑는다면 `start` 인자를 사용하여 중복과 역순 탐색을 방지하는 것이 국룰입니다. 마지막에 조건 필터링만 잊지 마세요."
    }
]

def publish():
    print("🚀 노션 자동화 시작 (IM Master Style)...")
    for p in problems:
        try:
            print(f"📄 '{p['title']}' 페이지 생성 중...")
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
            
            # 파일 읽기
            file_path = Path(p['file'])
            if file_path.exists():
                code = file_path.read_text(encoding="utf-8")
                blocks.append(code_block(code))
            else:
                blocks.append(callout_block(f"파일을 찾을 수 없습니다: {p['file']}", emoji="⚠️"))
            
            blocks.append(divider_block())
            blocks.append(heading_block("💡 학생 가이드", level=2))
            blocks.append(callout_block(p['guide'], emoji="💡"))
            
            # 노션 블록 삽입 (Chunking 적용)
            append_blocks(page_id, blocks)
            print(f"✅ '{p['title']}' 업로드 완료! (ID: {page_id})")
            
        except Exception as e:
            print(f"❌ '{p['title']}' 처리 중 오류 발생: {e}")
        
        time.sleep(1) # API 부하 방지

if __name__ == "__main__":
    publish()
