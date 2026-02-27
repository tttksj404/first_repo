import requests
import time
import json


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

def update_notion_final():
    # 1. 원본 파일에서 새로 작성된 '퍼펙트' 코드 읽기
    with open('gitp/BFS/2573끝판왕 bfs 동시탐색시 시간초과 따라서 변동값 리스트 저장.py', 'r', encoding='utf-8') as f:
        verbatim_code = f.read()

    # 2. 노션용 블록 구성
    blocks = [
        {'type': 'divider', 'divider': {}},
        {'type': 'heading_1', 'heading_1': {'rich_text': [{'type': 'text', 'text': {'content': '📍 [Samsung A] 빙산 - BFS 기반 동시 시뮬레이션 (최종 완성본)'}}]}},
        {'type': 'quote', 'quote': {'rich_text': [{'type': 'text', 'text': {'content': 'IM 초월 최적화 전략(명단 관리, 예약 시스템, 다이어트 기법)이 100% 반영된 최종 정답 코드와 상세 해설입니다.'}}]}},
        {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '💻 Python 전체 정답 코드 (고밀도 상세 주석)'}}]}},
        {'type': 'code', 'code': {'language': 'python', 'rich_text': [{'type': 'text', 'text': {'content': verbatim_code.strip()}}]}},
        {'type': 'callout', 'callout': {'icon': {'type': 'emoji', 'emoji': '💡'}, 'rich_text': [{'type': 'text', 'text': {'content': '학생 가이드: 9만 칸 전수 조사 대신 ice_list(명단)를 활용하는 습관이 A형 합격의 핵심입니다. 스냅샷 기법을 통해 동시성 처리를 완벽히 구현하세요.'}}]}}
    ]

    # 3. 기존 블록 삭제 (중복 방지 및 교체)
    url = f'https://api.notion.com/v1/blocks/{PAGE_ID}/children'
    res = requests.get(url, headers=HEADERS)
    all_blocks = res.json().get('results', [])
    
    target_start_index = -1
    for i, b in enumerate(all_blocks):
        if b['type'] == 'heading_1' and '빙산' in b['heading_1']['rich_text'][0]['plain_text']:
            target_start_index = i
            break
            
    if target_start_index != -1:
        print(f"Cleaning up old blocks from index {target_start_index}...")
        for b in all_blocks[target_start_index:]:
            requests.delete(f'https://api.notion.com/v1/blocks/{b["id"]}', headers=HEADERS)
            time.sleep(0.1)

    # 4. 새로운 콘텐츠 추가
    for i in range(0, len(blocks), 5):
        chunk = blocks[i:i+5]
        requests.patch(url, headers=HEADERS, json={'children': chunk})
        time.sleep(1)
    print("Success: Notion updated with the rewritten perfect Iceberg code.")

if __name__ == '__main__':
    update_notion_final()
