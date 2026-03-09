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
PARENT_PAGE_ID = "303eacc8-175a-80a3-9154-f7a7acee7c80" # 코테 대비 페이지 ID

def api_request(method, path, payload=None):
    url = f"https://api.notion.com/v1{path}"
    for attempt in range(1, 6):
        try:
            response = requests.request(method, url, headers=HEADERS, json=payload, timeout=30)
            if response.status_code == 429:
                wait_time = 2**attempt
                print(f"Rate limited. Waiting {wait_time}s...")
                time.sleep(wait_time)
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
        },
        "icon": {"type": "emoji", "emoji": "👑"}
    }
    return api_request("POST", "/pages", payload)

def append_blocks(block_id, blocks):
    # 5~10개 단위로 쪼개어 보내는 Chunking 적용
    for i in range(0, len(blocks), 5):
        chunk = blocks[i:i+5]
        api_request("PATCH", f"/blocks/{block_id}/children", {"children": chunk})
        time.sleep(0.5)

def rich_text_list(content, bold=False, color=None):
    # 2000자 제한을 위한 2중 청킹 프로토콜
    res = []
    chunk_size = 1900
    for i in range(0, len(content), chunk_size):
        text_part = content[i:i+chunk_size]
        item = {"type": "text", "text": {"content": text_part}}
        if bold or color:
            item["annotations"] = {}
            if bold: item["annotations"]["bold"] = True
            if color: item["annotations"]["color"] = color
        res.append(item)
    return res

def text_block(content, bold=False, color=None):
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text_list(content, bold, color)}
    }

def heading_block(content, level=2):
    t = f"heading_{level}"
    return {
        "object": "block",
        "type": t,
        t: {"rich_text": rich_text_list(content, bold=True)}
    }

def callout_block(content, emoji="💡", color="default"):
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": emoji},
            "rich_text": rich_text_list(content),
            "color": color
        }
    }

def quote_block(content):
    return {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": rich_text_list(content)}
    }

def bullet_block(content, bold=False):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text_list(content, bold)}
    }

def code_block(code, language="python"):
    return {
        "object": "block",
        "type": "code",
        "code": {
            "language": language,
            "rich_text": rich_text_list(code)
        }
    }

def divider_block():
    return {"object": "block", "type": "divider", "divider": {}}

def todo_block(content):
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": rich_text_list(content)}
    }

def publish():
    title = "[A형 합격] 재귀, 브루트포스, 백트래킹 백지코딩 끝판왕 정복"
    print(f"🚀 '{title}' 페이지 생성 중...")
    
    page = create_page(title, PARENT_PAGE_ID)
    page_id = page['id']
    
    blocks = []
    
    # 상단 요약 및 상황 설정
    blocks.append(callout_block("이 가이드는 단순 암기가 아닌, '재귀적 사고의 시각화'와 '백트래킹의 복구 메커니즘'을 완벽히 이해하도록 설계되었습니다. 삼성 A형의 80%는 여기서 나옵니다.", emoji="🔥", color="yellow_background"))
    blocks.append(quote_block("순열, 조합, 부분집합... 매번 헷갈린다면? 백트래킹의 '원상복구' 원리만 알면 모든 구현이 가능합니다. 이 가이드는 '머릿속의 로직을 코드로 옮기는 법'을 알려드립니다."))
    blocks.append(divider_block())

    # Section 1
    blocks.append(heading_block("🔍 1. 재귀(Recursion) - 백트래킹의 심장", level=2))
    blocks.append(text_block("재귀는 '함수가 자기 자신을 호출하는 것'입니다. 마치 마트료시카 인형처럼 큰 문제를 해결하기 위해 똑같은 형태의 작은 문제로 들어가는 과정이죠.", bold=True))
    blocks.append(text_block("📍 재귀의 2대 필수 조건 (절대 원칙)", bold=True))
    blocks.append(bullet_block("기저 조건 (Base Case): '언제 멈출 것인가?' (탈출구). 이게 없으면 RecursionError가 발생합니다."))
    blocks.append(bullet_block("유도 파트 (Inductive Step): '어떻게 다음 단계로 나아갈 것인가?' (진입로). 문제를 작게 만들어 다시 자신을 호출합니다."))
    blocks.append(callout_block("시각화 팁: 재귀는 '지하실로 내려가는 계단'과 같습니다. 바닥(기저 조건)을 찍어야 다시 1층으로 올라올 수 있습니다.", emoji="🪜"))
    blocks.append(divider_block())

    # Section 2
    blocks.append(heading_block("🔍 2. 브루트포스(Brute Force) - 무식하게 다 해보기", level=2))
    blocks.append(text_block("삼성 A형은 입력값 N이 보통 10~15 정도로 작습니다. 이는 '모든 경우의 수를 다 뒤져봐라'라는 강력한 힌트입니다."))
    blocks.append(bullet_block("N! (순열) 이나 2^N (부분집합) 정도의 복잡도는 N=10 수준에서 충분히 통과 가능합니다."))
    blocks.append(bullet_block("Greedy나 DP가 먼저 떠오르지 않는다면, 일단 '재귀'로 모든 경우를 다 해보는 것부터 시작하세요."))
    blocks.append(divider_block())

    # Section 3
    blocks.append(heading_block("🔍 3. 백트래킹(Backtracking) - 똑똑하게 다 해보기", level=2))
    blocks.append(text_block("백트래킹은 모든 경로를 가보되, '이 길은 아니네?' 싶을 때 즉시 되돌아오는 기술입니다.", bold=True))
    blocks.append(text_block("📍 핵심 메커니즘: '선택' -> '탐색' -> '복구'", bold=True))
    blocks.append(bullet_block("가지치기 (Pruning): 유망하지 않은 경로는 중간에 return 하여 시간을 단축합니다. 예: 합이 이미 최솟값을 넘었을 때."))
    blocks.append(bullet_block("상태 복구 (Restoration): [가장 중요] 재귀가 끝난 뒤에는 나의 선택(방문 체크 등)을 반드시 '취소'해야 다른 갈림길에서 영향을 받지 않습니다."))
    blocks.append(divider_block())

    # Section 4: Pruning
    blocks.append(heading_block("🔍 4. 가지치기(Pruning) - A형 합격의 당락을 가르는 기술", level=2))
    blocks.append(quote_block("단순히 다 해보는 것만으로는 시간 초과(TLE)를 피할 수 없을 때가 있습니다. 이때 '미리 싹을 자르는' 것이 필요합니다."))
    blocks.append(bullet_block("최소값 갱신 중일 때: 현재까지의 합(sum)이 이미 이전에 구한 최소값(ans)보다 크다면? 더 가볼 필요 없이 즉시 return!"))
    blocks.append(bullet_block("특정 조건 위배: 문제에서 요구하는 조건(예: 특정 좌표 방문 불가)을 어기는 순간 즉시 return!"))
    blocks.append(divider_block())

    # 3대 패턴
    blocks.append(heading_block("🏗️ 백트래킹 3대 패턴 (순열, 조합, 부분집합)", level=2))
    
    blocks.append(text_block("1️⃣ 순열 (Permutation) - '순서가 다르면 다른 것'", bold=True, color="blue"))
    blocks.append(text_block("예: (A, B) ≠ (B, A). 핵심은 visited 배열로 사용 여부 체크 + 항상 0번부터 탐색."))
    blocks.append(code_block("""# [순열 템플릿]
def perm(depth):
    if depth == R: # R개를 다 뽑았다면?
        print(path) # 정답 처리
        return

    for i in range(N): # 항상 0부터 끝까지 검사
        if not visited[i]: # 아직 안 썼다면?
            visited[i] = True  # [선택]
            path.append(data[i])
            perm(depth + 1)    # [탐색]
            path.pop()         # [복구]
            visited[i] = False # [복구]"""))

    blocks.append(text_block("2️⃣ 조합 (Combination) - '순서가 달라도 같은 것'", bold=True, color="green"))
    blocks.append(text_block("예: (A, B) = (B, A). 핵심은 start 인덱스를 인자로 넘겨 '나보다 뒤에 있는 애들만 봐라'고 지시."))
    blocks.append(code_block("""# [조합 템플릿]
def comb(depth, start):
    if depth == R:
        print(path)
        return

    for i in range(start, N): # start부터 끝까지 검사 (이전 선택 제외)
        path.append(data[i])
        comb(depth + 1, i + 1) # 다음은 i+1부터 봐라!
        path.pop() # [복구]"""))

    blocks.append(text_block("3️⃣ 부분집합 (Power Set) - '넣을까? 말까?'", bold=True, color="orange"))
    blocks.append(text_block("모든 요소에 대해 '포함/미포함'의 2가지 선택지를 가집니다. (2^N)"))
    blocks.append(code_block("""# [부분집합 템플릿]
def subset(depth):
    if depth == N:
        # selected에 True인 애들만 모으면 하나의 부분집합 완성
        return

    selected[depth] = True  # 현재 원소 포함
    subset(depth + 1)
    
    selected[depth] = False # 현재 원소 미포함
    subset(depth + 1)"""))
    blocks.append(divider_block())

    # 실전 예시 1
    blocks.append(heading_block("🏗️ 실전 예제 1 - [BOJ 14889 스타트와 링크]", level=2))
    blocks.append(quote_block("N명 중 N/2명을 뽑는 '조합'과 팀 점수 계산 '시뮬레이션'이 결합된 최고의 연습 문제입니다."))
    
    code_14889 = Path("gitp/A형준비/Step2_BruteForce_Backtracking/14889.py").read_text(encoding="utf-8")
    blocks.append(code_block(code_14889))
    
    blocks.append(divider_block())

    # 실전 예시 2
    blocks.append(heading_block("🏗️ 실전 예제 2 - [BOJ 14888 연산자 끼워넣기]", level=2))
    blocks.append(quote_block("숫자 순서는 고정, 연산자의 순열을 구하는 문제입니다. 남은 연산자 개수를 인자로 넘기는 테크닉을 배울 수 있습니다."))
    
    code_14888 = Path("gitp/A형준비/Step2_BruteForce_Backtracking/14888.py").read_text(encoding="utf-8")
    blocks.append(code_block(code_14888))

    blocks.append(divider_block())

    # 체크리스트 및 가이드
    blocks.append(heading_block("🏗️ 구현 체크리스트", level=2))
    blocks.append(todo_block("기저 조건(Base Case)이 정확한가? (depth == N)"))
    blocks.append(todo_block("유도 파트가 모든 후보를 포함하는가? (for i in range...)"))
    blocks.append(todo_block("Visited 배열이나 Index 관리가 적절한가?"))
    blocks.append(todo_block("재귀 호출 직후 상태 복구(Pop, visited=False)를 했는가?"))
    
    blocks.append(divider_block())
    blocks.append(heading_block("💡 학생 가이드: 백지코딩을 위한 멘탈 모델", level=2))
    blocks.append(callout_block("재귀가 꼬인다면? print('  ' * depth, f'depth: {depth}') 처럼 depth만큼 공백을 주어 출력해 보세요. 함수가 어떻게 들어갔다 나오는지 계단식으로 보일 겁니다.", emoji="🧪"))
    blocks.append(callout_block("시간 초과가 난다면? 기저 조건에 도달하기 전이라도 '이미 정답의 가능성이 없는 경우(예: 현재 합 > 최소 합)' 바로 return 하는 '가지치기'를 추가하세요.", emoji="✂️"))
    
    append_blocks(page_id, blocks)
    print(f"✅ '{title}' 업로드 완료!")

if __name__ == "__main__":
    publish()
