import requests
import os
import json
import time

TOKEN = os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
MASTERBOOK_ID = "31eeacc8-175a-8183-b982-f39616d86dce"

def api_request(method, path, payload=None):
    url = f"https://api.notion.com/v1{path}"
    res = requests.request(method, url, headers=HEADERS, json=payload)
    res.raise_for_status()
    return res.json()

def create_subpage(title, parent_id, emoji="🐍"):
    payload = {
        "parent": {"page_id": parent_id},
        "properties": {"title": {"title": [{"text": {"content": title}}]}},
        "icon": {"type": "emoji", "emoji": emoji}
    }
    return api_request("POST", "/pages", payload)

def append_blocks(block_id, blocks):
    for i in range(0, len(blocks), 50):
        api_request("PATCH", f"/blocks/{block_id}/children", {"children": blocks[i:i+50]})
        time.sleep(0.5)

def rich_text(content, bold=False, code=False):
    item = {"type": "text", "text": {"content": content}}
    if bold or code:
        item["annotations"] = {}
        if bold: item["annotations"]["bold"] = True
        if code: item["annotations"]["code"] = True
    return [item]

def para(content):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]}}

def callout(content, emoji="💡"):
    return {"object": "block", "type": "callout", "callout": {"icon": {"type": "emoji", "emoji": emoji}, "rich_text": [{"type": "text", "text": {"content": content}}]}}

def code_blk(code, lang="python"):
    return {"object": "block", "type": "code", "code": {"language": lang, "rich_text": [{"type": "text", "text": {"content": code}}]}}

def main():
    print("🚀 Creating Syntax Mastery Subpages...")
    
    # 1. Fast I/O
    p1 = create_subpage("🐍 [Syntax 1] Fast I/O & String Magic", MASTERBOOK_ID)
    append_blocks(p1['id'], [
        callout("삼성 A형/SWEA는 입력량이 많아 sys.stdin.readline이 필수인 경우가 있습니다."),
        para("📍 Fast I/O 사용법"),
        code_blk("import sys\ninput = sys.stdin.readline\n\n# 한 줄 읽고 정수로 변환\nN = int(input())\n\n# 공백으로 구분된 여러 정수 읽기\narr = list(map(int, input().split()))"),
        para("📍 문자열 처리 (strip, join)"),
        code_blk("s = input().strip() # 앞뒤 공백 제거\nwords = ['Hello', 'World']\nprint(' '.join(words)) # Hello World")
    ])
    
    # 2. Matrix
    p2 = create_subpage("🐍 [Syntax 2] List & Matrix Mastery (2D Grid)", MASTERBOOK_ID)
    append_blocks(p2['id'], [
        callout("격자(Grid) 문제는 '전치(Transpose)'와 '회전'이 핵심입니다."),
        para("📍 2차원 배열 회전 (zip 활용)"),
        code_blk("# 시계방향 90도 회전\nrotated = list(zip(*original[::-1]))\n\n# 반시계방향 90도 회전\nrotated = list(zip(*original))[::-1]"),
        para("📍 2차원 배열 초기화 주의사항"),
        code_blk("# [잘못된 예] 모든 행이 같은 객체를 참조하게 됨\nvisited = [[False] * M] * N \n\n# [올바른 예] List Comprehension 사용\nvisited = [[False] * M for _ in range(N)]")
    ])
    
    # 3. DS
    p3 = create_subpage("🐍 [Syntax 3] Data Structures (Deque, Heapq, Set)", MASTERBOOK_ID)
    append_blocks(p3['id'], [
        callout("BFS는 deque, 최단경로는 heapq, 중복체크는 set을 사용하세요."),
        para("📍 Deque (Queue 구현)"),
        code_blk("from collections import deque\nq = deque([1, 2, 3])\nq.append(4)\nq.popleft() # 1 반환 (O(1))"),
        para("📍 Set (O(1) 검색)"),
        code_blk("s = set([1, 2, 3])\nif 2 in s: # O(1)\n    print('Exists!')")
    ])

    print("✅ All Syntax Subpages created and linked!")

if __name__ == "__main__":
    main()
