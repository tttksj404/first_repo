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

def update_notion_verbatim():
    # 1. 원본 파일에서 코드와 주석 읽기
    with open('gitp/BFS/2573끝판왕 bfs 동시탐색시 시간초과 따라서 변동값 리스트 저장.py', 'r', encoding='utf-8') as f:
        verbatim_code = f.read()

    # 2. 전략 분석 텍스트 구성
    strategy_analysis = """
### 🔍 [IM 초월] 3단계 핵심 전략 분석 (사용자 원본 가이드)

**1단계: "범인은 이 안에 있어!" (좌표 리스트 활용)**
*   형사가 범인을 잡으러 갈 때, 도시 전체 9만 가구를 집집마다 방문(이중 for문)하면 시간이 너무 오래 걸리겠죠?
*   대신 **"용의자 명단(ice_list)"**만 들고 그 집들만 찾아가는 게 훨씬 빠릅니다.
*   **결과**: 매년 루프를 돌 때마다 확인하는 칸이 90,000개에서 수백 개로 확 줄어듭니다.

**2단계: "스냅샷 찍기" (예약 시스템)**
*   빙산 하나가 녹아 0이 되는 순간 옆 칸의 결과에 영향을 줍니다. 하지만 문제는 "동시에" 녹는 것을 원하죠.
*   "지금 바로 지도를 고치면 다음 칸 계산이 꼬인다. 그러니 '누가 얼마나 녹을지' 메모지(melt_list)에 일단 적어만 두자. 조사가 다 끝나면 그때 한꺼번에 지도를 고치자(Batch Update)."
*   **결과**: 연쇄 반응 오류를 막고 데이터의 일관성을 유지합니다.

**3단계: "다이어트 시키기" (리스트 갱신)**
*   명단에 있는 용의자가 이미 감옥에 갔거나 사라졌다면, 내년 명단에서는 빼야 합니다.
*   올해 녹아서 0이 된 애들은 내년엔 검사할 필요가 없잖아? 내년용 새 명단(next_ice_list)을 만들어서 살아남은 애들만 옮겨 담자.
*   **결과**: 시간이 지날수록 검사할 대상이 줄어들어 속도가 점점 더 빨라집니다.
"""

    blocks = [
        {'type': 'divider', 'divider': {}},
        {'type': 'heading_1', 'heading_1': {'rich_text': [{'type': 'text', 'text': {'content': '📍 [Samsung A] 빙산 - BFS 기반 동시 시뮬레이션 (원본 주석 100% 보전)'}}]}},
        {'type': 'quote', 'quote': {'rich_text': [{'type': 'text', 'text': {'content': '원본 파일의 코드 내 주석("쪽지", "바다의 개수만큼", "0미만 방어" 등)을 한 글자도 빠짐없이 완벽하게 복제했습니다.'}}]}},
        {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '🔍 핵심 전략 및 생각의 흐름'}}]}},
        {'type': 'paragraph', 'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': strategy_analysis.strip()}}]}},
        {'type': 'heading_2', 'heading_2': {'rich_text': [{'type': 'text', 'text': {'content': '💻 Python 정답 코드 (원본 주석 포함)'}}]}},
        {'type': 'code', 'code': {'language': 'python', 'rich_text': [{'type': 'text', 'text': {'content': verbatim_code.strip()}}]}},
        {'type': 'callout', 'callout': {'icon': {'type': 'emoji', 'emoji': '💡'}, 'rich_text': [{'type': 'text', 'text': {'content': '학생 가이드: 원본 코드의 주석이야말로 실전에서 떠올려야 할 "생각의 지도"입니다. 9만 칸 대신 명단만 확인하는 최적화 기법을 완벽히 숙지하세요.'}}]}}
    ]

    # 3. 기존 블록 삭제 (중복 방지)
    url = f'https://api.notion.com/v1/blocks/{PAGE_ID}/children'
    res = requests.get(url, headers=HEADERS)
    all_blocks = res.json().get('results', [])
    
    target_start_index = -1
    for i, b in enumerate(all_blocks):
        if b['type'] == 'heading_1' and '빙산' in b['heading_1']['rich_text'][0]['plain_text']:
            target_start_index = i
            break
            
    if target_start_index != -1:
        print(f"Cleaning up blocks from index {target_start_index}...")
        for b in all_blocks[target_start_index:]:
            requests.delete(f'https://api.notion.com/v1/blocks/{b["id"]}', headers=HEADERS)
            time.sleep(0.1)

    # 4. 100% 보존된 콘텐츠 추가
    for i in range(0, len(blocks), 5):
        chunk = blocks[i:i+5]
        requests.patch(url, headers=HEADERS, json={'children': chunk})
        time.sleep(1)
    print("Success: Updated Notion with 100% verbatim comments from the original file.")

if __name__ == '__main__':
    update_notion_verbatim()
