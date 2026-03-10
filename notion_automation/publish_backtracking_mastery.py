import json
import requests
import time
from notion_automation.core.notion_env import get_notion_token

NOTION_TOKEN = get_notion_token()
NOTION_VERSION = "2022-06-28"
PARENT_PAGE_ID = "2f0eacc8175a80728e4be298edcb69c5"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION
}

def create_page(parent_id, title):
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": [{"text": {"content": title}}]
        }
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()["id"]
    else:
        print(f"Error creating page: {response.text}")
        return None

def append_blocks(page_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    for i in range(0, len(blocks), 10):
        chunk = blocks[i:i+10]
        for attempt in range(5):
            resp = requests.patch(url, headers=headers, json={"children": chunk})
            if resp.status_code == 200: break
            time.sleep(2 ** attempt)
        time.sleep(0.5)

def rich_text(text):
    return [{"type": "text", "text": {"content": text[i:i+1900]}} for i in range(0, len(text), 1900)]

def heading(text, level=1):
    return {"object": "block", "type": f"heading_{level}", f"heading_{level}": {"rich_text": [{"type": "text", "text": {"content": text}}]}}

def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}

def callout(text, emoji="💡", color="default"):
    return {"object": "block", "type": "callout", "callout": {"rich_text": rich_text(text), "icon": {"emoji": emoji}, "color": color}}

def code(text, lang="python"):
    return {"object": "block", "type": "code", "code": {"rich_text": rich_text(text), "language": lang}}

def bullet(text):
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich_text(text)}}

def divider(): return {"object": "block", "type": "divider", "divider": {}}

def main():
    title = "📕 [마스터북] 백트래킹 3대 천왕 (순열, 조합, 부분집합) - IM 마스터 가이드"
    page_id = create_page(PARENT_PAGE_ID, title)
    if not page_id: return

    # Intro
    intro = [
        callout("백트래킹은 모든 경우의 수를 '체계적으로' 탐색하는 기술입니다. 삼성 A형의 핵심이며, 순열/조합/부분집합의 템플릿만 완벽히 외우면 80%는 해결됩니다.", emoji="🚀", color="blue_background"),
        {"object": "block", "type": "table_of_contents", "table_of_contents": {}},
        divider()
    ]
    append_blocks(page_id, intro)

    # 1. Permutation
    perm = [
        heading("1. 순열 (Permutations)", 1),
        callout("순서가 중요하다! (1, 2)와 (2, 1)은 서로 다른 경우로 취급합니다.", emoji="🔢"),
        heading("🔍 핵심 접근법", 2),
        paragraph("- **핵심 아이템**: `visited` (또는 `used`) 배열.\n- **동작 원리**: 0번 인덱스부터 끝까지 매번 훑지만, 이미 뽑은 녀석(`visited[i] == True`)은 건너뜁니다."),
        heading("💻 표준 템플릿", 2),
        code("""def dfs(depth):
    if depth == M: # M개를 다 뽑았다면?
        print(path)
        return

    for i in range(N):
        if not visited[i]: # 아직 안 썼다면
            visited[i] = True
            path.append(nums[i]) # 선택!
            
            dfs(depth + 1) # 다음 칸으로
            
            path.pop() # 백트래킹 (선택 취소)
            visited[i] = False"""),
        heading("📍 관련 문제 리스트", 2),
        bullet("`10974.py` (모든 순열) - 가장 기본적인 N! 탐색"),
        bullet("`14888.py` (연산자 끼워넣기) - 연산자들의 순열을 만드는 문제"),
        bullet("`A형실전_15649_N과M1_순열.py` - 백트래킹의 기초"),
        bullet("`worksplit.py` (일 분배) - 누구에게 어떤 일을 맡길지 순열 결정"),
        bullet("`electrocart.py` (전자카트) - 경로의 순서를 결정하는 TSP 유형"),
        bullet("`maxcontestmoney.py` (최대 상금) - 숫자판 교환(순열 기반 교환)"),
        divider()
    ]
    append_blocks(page_id, perm)

    # 2. Combination
    comb = [
        heading("2. 조합 (Combinations)", 1),
        callout("순서는 상관없다! (1, 2)와 (2, 1)은 같은 팀입니다. 대표 뽑기 유형.", emoji="🤝"),
        heading("🔍 핵심 접근법", 2),
        paragraph("- **핵심 아이템**: `start` 인자.\n- **동작 원리**: `for` 루프를 `start`부터 시작하여, 이전에 뽑은 인덱스보다 뒤에 있는 것만 고려합니다. (자동으로 오름차순 형성)"),
        heading("💻 표준 템플릿", 2),
        code("""def dfs(depth, start):
    if depth == M:
        print(path)
        return

    for i in range(start, N):
        path.append(nums[i]) # 선택!
        
        # 다음 재귀는 현재 인덱스(i)의 '다음(i+1)'부터 탐색!
        dfs(depth + 1, i + 1) 
        
        path.pop() # 백트래킹"""),
        heading("📍 관련 문제 리스트", 2),
        bullet("`1759.py` (암호 만들기) - 자음/모음 조건이 붙은 조합"),
        bullet("`6603.py` (로또) - 6개의 숫자를 고르는 전형적인 조합"),
        bullet("`14889.py` (스타트와 링크) - 팀을 N/2명씩 나누는 조합"),
        bullet("`minsum.py` (최소합) - 경로 선택에서의 조합적 접근"),
        bullet("`A형필수_순열조합_중복제거백트래킹.py` - 기본 개념 총정리"),
        divider()
    ]
    append_blocks(page_id, comb)

    # 3. Subset
    subset = [
        heading("3. 부분집합 (Subsets)", 1),
        callout("각 원소에게 묻는다: '너 들어올래? 말래?' (Yes or No)", emoji="🧺"),
        heading("🔍 핵심 접근법", 2),
        paragraph("- **핵심 아이템**: `Binary Choice` (포함/미포함).\n- **동작 원리**: `for`문 없이, 현재 인덱스 원소를 '넣는 재귀'와 '안 넣는 재귀'를 각각 호출합니다."),
        heading("💻 표준 템플릿", 2),
        code("""def dfs(idx, current_sum):
    if idx == N: # 끝까지 다 물어봤다면?
        if current_sum == S: # 조건 확인
            print(path)
        return

    # 1. 현재 원소(nums[idx])를 포함하는 경우
    path.append(nums[idx])
    dfs(idx + 1, current_sum + nums[idx])
    path.pop() # 백트래킹

    # 2. 현재 원소를 포함하지 않는 경우
    dfs(idx + 1, current_sum)"""),
        heading("📍 관련 문제 리스트", 2),
        bullet("`1182.py` (부분수열의 합) - 부분집합 합의 정석"),
        bullet("`highestsheelves.py` (장훈이의 높은 선반) - 모든 부분집합 합 중 최소 초과값 찾기"),
        divider()
    ]
    append_blocks(page_id, subset)

    # Final Tips
    tips = [
        heading("💡 IM Master의 실전 팁", 1),
        callout("중복을 허용하는가? (중복순열/중복조합)", emoji="⚠️", color="yellow_background"),
        bullet("**중복순열**: `visited` 체크를 안 하면 됩니다."),
        bullet("**중복조합**: `dfs` 호출 시 `i+1`이 아니라 현재 인덱스 `i`를 그대로 넘기면 됩니다."),
        callout("시간 복잡도 계산법", emoji="⏳", color="gray_background"),
        bullet("순열: N! (N=10 정도가 한계)"),
        bullet("조합: NCr (N=20~30 정도가 한계)"),
        bullet("부분집합: 2^N (N=20 정도가 한계)"),
        paragraph("\n**가장 중요한 것**: 재귀 호출이 끝난 뒤 반드시 `path.pop()`이나 `visited[i] = False`로 원상 복구하세요. 이것이 백트래킹의 알파이자 오메가입니다.")
    ]
    append_blocks(page_id, tips)

    print(f"Master Book Created! https://www.notion.so/{page_id.replace('-', '')}")

if __name__ == "__main__":
    main()
