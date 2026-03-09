import requests
import os
import json
import time
from pathlib import Path

# --- 인증 및 설정 ---
TOKEN = os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PAGE_ID = "1677d48e-73f4-4e05-976d-0da8d115ccf0"

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

def append_blocks(block_id, blocks):
    for i in range(0, len(blocks), 10):
        chunk = blocks[i:i+10]
        api_request("PATCH", f"/blocks/{block_id}/children", {"children": chunk})
        time.sleep(0.5)

def rich_text_list(content, bold=False, color=None):
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
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text_list(content, bold, color)}}

def heading_block(content, level=2):
    t = f"heading_{level}"
    return {"object": "block", "type": t, t: {"rich_text": rich_text_list(content, bold=True)}}

def quote_block(content):
    return {"object": "block", "type": "quote", "quote": {"rich_text": rich_text_list(content)}}

def bullet_block(content, bold=False):
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich_text_list(content, bold)}}

def code_block(code, language="python"):
    return {"object": "block", "type": "code", "code": {"language": language, "rich_text": rich_text_list(code)}}

def divider_block():
    return {"object": "block", "type": "divider", "divider": {}}

def publish_additional():
    print(f"🚀 추가 BruteForce 파트 업로드 중...")
    
    blocks = []
    blocks.append(divider_block())
    blocks.append(heading_block("🏗️ 추가 실전 예제 - BruteForce & Backtracking 심화", level=2))

    # 예제 3: 암호 만들기
    blocks.append(heading_block("3️⃣ [BOJ 1759] 암호 만들기 (조합 + 조건 검사)", level=3))
    blocks.append(quote_block("정렬된 문자들 중 L개를 뽑는 '조합' 문제입니다. 모음 1개, 자음 2개 이상의 조건을 체크하는 것이 핵심입니다."))
    code_1759 = Path("gitp/A형준비/Step2_BruteForce_Backtracking/1759.py").read_text(encoding="utf-8")
    blocks.append(code_block(code_1759))

    # 예제 4: 부분수열의 합
    blocks.append(heading_block("4️⃣ [BOJ 1182] 부분수열의 합 (부분집합)", level=3))
    blocks.append(quote_block("각 원소를 '넣을까 말까' 결정하는 부분집합(Power Set)의 전형적인 문제입니다. 2^N의 시간 복잡도를 이해하는 데 최적입니다."))
    code_1182 = Path("gitp/A형준비/Step2_BruteForce_Backtracking/1182.py").read_text(encoding="utf-8")
    blocks.append(code_block(code_1182))

    # 예제 5: 전자카트
    blocks.append(heading_block("5️⃣ [Samsung A] 전자카트 (순열 & TSP)", level=3))
    blocks.append(quote_block("1번 방에서 출발하여 모든 방을 거쳐 다시 1번으로 돌아오는 최단 경로를 구합니다. 순열(Permutation)로 경로를 짜고 합을 구하는 기초 TSP 유형입니다."))
    code_electro = Path("gitp/A형준비/Step2_BruteForce_Backtracking/electrocart.py").read_text(encoding="utf-8")
    blocks.append(code_block(code_electro))

    # 예제 6: 최소합
    blocks.append(heading_block("6️⃣ [Samsung A] 최소합 (DFS & 가지치기)", level=3))
    blocks.append(quote_block("격자판의 왼쪽 위에서 오른쪽 아래까지 이동하며 숫자의 합을 최소화합니다. DFS 탐색 중 현재 합이 이미 최소값을 넘었다면 중단하는 '가지치기'를 배울 수 있습니다."))
    code_minsum = Path("gitp/A형준비/Step2_BruteForce_Backtracking/minsum.py").read_text(encoding="utf-8")
    blocks.append(code_block(code_minsum))

    append_blocks(PAGE_ID, blocks)
    print(f"✅ 추가 예제 업로드 완료!")

if __name__ == "__main__":
    publish_additional()
