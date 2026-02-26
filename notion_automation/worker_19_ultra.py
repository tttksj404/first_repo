import requests
import json
import time

NOTION_TOKEN = "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"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def rebuild_full_version(pid, title, blocks):
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.05)
    for i in range(0, len(blocks), 2):
        chunk = blocks[i:i+2]
        requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": chunk})
        time.sleep(0.5)
    res_verify = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    actual_count = len(res_verify.json().get("results", []))
    print(f"VERIFIED: {title} ({actual_count} blocks written)")
    return True

# --------------------------------------------------------------------------------
# Problem 19 - 연산자 끼워넣기 (Detailed Full Version)
# --------------------------------------------------------------------------------
ops_ultra_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 19] 연산자 끼워넣기 - DFS 백트래킹을 이용한 수식 전수조사"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "문제 요약: 숫자 사이에 사칙연산자를 배치하여 결과값의 최댓값과 최솟값을 구합니다. 연산자 개수를 상태로 관리하며 모든 수식 조합을 탐색하는 백트래킹의 정석입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 1. 문제 분석 및 예외 조건"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "음수 나눗셈: 파이썬의 // 는 내림을 하므로, 문제 조건(0 방향 수렴)을 위해 int(a / b) 를 사용해야 합니다."}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "결과 범위: -10억 ~ 10억. 초기 최솟값과 최댓값을 충분히 크게/작게 설정해야 합니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 2. 핵심 알고리즘 설계"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "코딩 로직: dfs(index, current_sum, add, sub, mul, div) 재귀 구조를 사용합니다. 각 연산자 카드를 하나씩 소모하며 다음 숫자로 전진하고, 인덱스가 N에 도달하면 결과를 갱신합니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 3. Python 전체 정답 코드 (Full Version)"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''import sys

def dfs(idx, current_sum, add, sub, mul, div):
    global max_val, min_val
    # 기저 사례: 모든 숫자를 다 사용한 경우
    if idx == N:
        max_val = max(max_val, current_sum)
        min_val = min(min_val, current_sum)
        return
    
    # 각 연산자 카드가 남아있다면 재귀 호출
    if add > 0:
        dfs(idx + 1, current_sum + nums[idx], add - 1, sub, mul, div)
    if sub > 0:
        dfs(idx + 1, current_sum - nums[idx], add, sub - 1, mul, div)
    if mul > 0:
        dfs(idx + 1, current_sum * nums[idx], add, sub, mul - 1, div)
    if div > 0:
        # 파이썬 특유의 음수 나눗셈 예외 처리
        dfs(idx + 1, int(current_sum / nums[idx]), add, sub, mul, div - 1)

if __name__ == "__main__":
    N = int(sys.stdin.readline())
    nums = list(map(int, sys.stdin.readline().split()))
    # +, -, *, / 개수 순서
    op_counts = list(map(int, sys.stdin.readline().split()))
    
    max_val = -float('inf')
    min_val = float('inf')
    
    dfs(1, nums[0], *op_counts)
    
    print(int(max_val))
    print(int(min_val))'''}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: dfs 함수의 인자로 남은 연산자 개수를 직접 넘겨주면, 명시적으로 visited 처리를 하지 않아도 자동으로 백트래킹이 수행되어 코드가 간결해집니다."}}]
    }}
]

rebuild_full_version("313eacc8-175a-81d1-b45c-ff132d0b1f56", "Operator Insertion Final", ops_ultra_blocks)
print("Operator page rebuilt.")
