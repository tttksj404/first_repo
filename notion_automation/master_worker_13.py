import requests
import json
import time

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def rebuild_and_verify(pid, title, blocks):
    print(f"--- [DEEP REBUILD START] {title} ---")
    # 1. Clear existing children
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.05)
    
    # 2. Patch in small chunks (3 blocks) for stability
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        for attempt in range(3):
            res = requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": chunk})
            if res.status_code == 200:
                print(f"Chunk {i//3 + 1} Success")
                break
            print(f"Retry {attempt+1}...")
            time.sleep(2)
        else:
            print("CRITICAL FAILURE: API Disconnected.")
            return False
        time.sleep(0.5)
    
    # 3. Final Content Verification
    res_verify = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    actual_count = len(res_verify.json().get("results", []))
    print(f"--- [SUCCESS] {title} Verified: {actual_count} blocks written. ---")
    return True

# --------------------------------------------------------------------------------
# Problem 13 - 마법사 상어와 파이어볼 (Ultra-Detailed)
# --------------------------------------------------------------------------------
fireball_full_content = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 13] 마법사 상어와 파이어볼 - 격자 순환 및 객체 분합 시뮬레이션"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "문제 요약: 파이어볼들이 각자의 속도와 방향으로 격자를 이동하며, 같은 칸에 모였을 때 합쳐지고 4개로 분할되는 과정을 구현합니다. 격자의 끝과 끝이 연결되어 있다는 점(Toroidal Grid)과 질량/속도/방향의 가중 평균 계산이 핵심입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 상황 상세 분석 (Constraints)"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "격자 연결성: 1번 행은 N번 행과 연결되어 있고, 1번 열은 N번 열과 연결되어 있습니다. 이를 위해 (r + dr*s) % N 연산이 반드시 필요합니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "분합 규칙: 한 칸에 2개 이상의 파이어볼이 모이면 1)질량 합/5 2)속도 합/개수 3)방향 결정 과정을 거칩니다. 이때 질량이 0이 되면 즉시 소멸합니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "방향 결정: 모인 파이어볼들의 방향이 모두 홀수이거나 모두 짝수이면 [0, 2, 4, 6], 그렇지 않으면 [1, 3, 5, 7] 방향으로 분사됩니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계 (Logic)"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "현실 로직: ", "annotations": {"bold": True}}, {"type": "text", "text": "모든 파이어볼에게 "각자 정해진 방향으로 가!"라고 명령한다. 이동이 끝나고 한 칸에 모여서 수다 떠는 놈들을 싹 다 잡아서 질량을 1/5로 줄이고 4개로 쪼개서 다시 날려 보낸다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "코딩 로직: ", "annotations": {"bold": True}}, {"type": "text", "text": "이동 후 좌표를 키(Key)로, 파이어볼 정보 리스트를 값(Value)으로 갖는 딕셔너리(defaultdict)를 사용한다. 딕셔너리를 순회하며 리스트 길이가 2 이상인 좌표에서만 합체 및 분할 로직을 적용한다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🏗️ 3. 구현 필수 체크리스트 (IM 스타일)"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "나머지 연산(% N): 이동 거리가 격자 크기보다 훨씬 클 수 있으므로 반드시 모듈로 연산을 적용했는가?"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "질량 0 처리: 나눗셈 결과 질량이 0이 되는 파이어볼은 리스트에 추가하지 않고 소멸시켰는가?"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "동시성 보장: 모든 파이어볼이 이동을 '마친 후에' 합체 로직이 돌아가는가? (이동 중에 합쳐지면 오답)"}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 4. Python 전체 정답 코드 (Full Version)"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''import sys
from collections import defaultdict

input = sys.stdin.readline
N, M, K = map(int, input().split())
fireballs = []
for _ in range(M):
    fireballs.append(list(map(int, input().split())))

# 8방향 정의 (0~7)
dr = [-1, -1, 0, 1, 1, 1, 0, -1]
dc = [0, 1, 1, 1, 0, -1, -1, -1]

for _ in range(K):
    # 1. 모든 파이어볼 이동 후 위치 수집
    new_pos = defaultdict(list)
    for r, c, m, s, d in fireballs:
        # 격자 연결성 처리 (% N)
        nr = (r + dr[d] * s) % N
        nc = (c + dc[d] * s) % N
        new_pos[(nr, nc)].append((m, s, d))
    
    # 2. 2개 이상 모인 칸 분합 로직
    next_fireballs = []
    for (r, c), fbs in new_pos.items():
        if len(fbs) >= 2:
            sum_m, sum_s, cnt = 0, 0, len(fbs)
            is_even, is_odd = True, True
            for m, s, d in fbs:
                sum_m += m
                sum_s += s
                if d % 2 == 0: is_odd = False
                else: is_even = False
            
            new_m = sum_m // 5
            if new_m == 0: continue # 질량 0 소멸
            new_s = sum_s // cnt
            # 방향 결정 (모두 짝/홀이면 0,2,4,6 아니면 1,3,5,7)
            new_dirs = [0, 2, 4, 6] if is_even or is_odd else [1, 3, 5, 7]
            for nd in new_dirs:
                next_fireballs.append((r, c, new_m, new_s, nd))
        else:
            # 1개인 칸은 그대로 유지
            m, s, d = fbs[0]
            next_fireballs.append((r, c, m, s, d))
    fireballs = next_fireballs

# 남은 질량의 합 출력
print(sum(f[2] for f in fireballs))'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "🎓"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 격자 시뮬레이션에서 '동시성'은 항상 새로운 자료구조(딕셔너리나 임시 맵)를 만들어 결과를 수집한 뒤 원본을 갱신하는 방식으로 해결하면 실수가 없습니다."}}]
    }}
]

rebuild_and_verify("313eacc8-175a-819e-a0b8-e6c64fc18bd1", "Fireball Shark", fireball_full_content)
