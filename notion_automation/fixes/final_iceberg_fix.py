import requests
import time
import json
import os


import os

def _get_notion_token():
    # Try multiple paths to find notion_key.txt
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(current_dir, 'notion_key.txt'),
        os.path.join(current_dir, '..', 'core', 'notion_key.txt'),
        os.path.join(current_dir, 'core', 'notion_key.txt'),
        os.path.join(os.getcwd(), 'notion_automation', 'core', 'notion_key.txt')
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                token = f.read().strip()
                if token: return token
    return os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")

NOTION_TOKEN = _get_notion_token()
PAGE_ID = '2f0eacc8-175a-805c-85b2-dca59899d3d8'
HEADERS = {
    'Authorization': f'Bearer {NOTION_TOKEN}',
    'Content-Type': 'application/json',
    'Notion-Version': '2022-06-28'
}

def fix():
    # 1. Read the code
    code_path = 'gitp/BFS/2573끝판왕 bfs 동시탐색시 시간초과 따라서 변동값 리스트 저장.py'
    with open(code_path, 'r', encoding='utf-8') as f:
        code_content = f.read()
    
    if not code_content.strip():
        print("ERROR: Code content is empty!")
        return

    # 2. Prepare blocks
    blocks = [
        {'type': 'divider', 'divider': {}},
        {'type': 'heading_1', 'heading_1': {'rich_text': [{'type': 'text', 'text': {'content': '📍 [Samsung A] 빙산 - BFS 기반 동시 시뮬레이션 (최종 완성본)'}}]}},
        {'type': 'quote', 'quote': {'rich_text': [{'type': 'text', 'text': {'content': 'IM 초월 최적화 전략(명단 관리, 예약 시스템, 다이어트 기법)이 100% 반영된 최종 정답 코드와 상세 해설입니다.'}}]}},
        {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '🔍 핵심 전략 가이드'}}]}},
        {'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'type': 'text', 'text': {'content': '1단계: "범인은 이 안에 있어!" (좌표 리스트 활용) - 9만 칸 전수 조사 대신 ice_list만 추적'}}]}},
        {'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'type': 'text', 'text': {'content': '2단계: "스냅샷 찍기" (예약 시스템) - 동시에 녹는 효과를 위해 melt_info에 저장 후 일괄 처리'}}]}},
        {'type': 'bulleted_list_item', 'bulleted_list_item': {'rich_text': [{'type': 'text', 'text': {'content': '3단계: "다이어트 시키기" (명단 갱신) - 이미 사라진 빙산은 다음 해 명단에서 제외'}}]}},
        {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '💻 Python 전체 정답 코드 (고밀도 상세 주석)'}}]}},
        {'type': 'code', 'code': {'language': 'python', 'rich_text': [{'type': 'text', 'text': {'content': code_content}}]}},
        {'type': 'callout', 'callout': {'icon': {'type': 'emoji', 'emoji': '💡'}, 'rich_text': [{'type': 'text', 'text': {'content': '학생 가이드: 9만 칸 전수 조사 대신 ice_list(명단)를 활용하는 습관이 A형 합격의 핵심입니다. 스냅샷 기법을 통해 동시성 처리를 완벽히 구현하세요.'}}]}}
    ]

    # 3. Append to Notion
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    print(f"Appending {len(blocks)} blocks to page {PAGE_ID}...")
    
    # Chunking for safety
    for i in range(0, len(blocks), 5):
        chunk = blocks[i:i+5]
        res = requests.patch(url, headers=HEADERS, json={'children': chunk})
        if res.status_code == 200:
            print(f"Chunk {i//5 + 1} appended successfully.")
        else:
            print(f"Error appending chunk {i//5 + 1}: {res.status_code} - {res.text}")
            return
        time.sleep(1)

    print("--- VERIFICATION ---")
    res_v = requests.get(url, headers=HEADERS)
    final_blocks = res_v.json().get('results', [])
    print(f"Final block count: {len(final_blocks)}")
    
    # Find the newly added heading
    found = False
    for b in final_blocks:
        if b['type'] == 'heading_1':
            rt = b['heading_1']['rich_text']
            if rt and '빙산' in rt[0]['plain_text']:
                print(f"FOUND HEADING: {rt[0]['plain_text']}")
                found = True
                break
    
    if found:
        print("VERIFICATION SUCCESSFUL.")
    else:
        print("VERIFICATION FAILED: Heading not found.")

if __name__ == "__main__":
    fix()
