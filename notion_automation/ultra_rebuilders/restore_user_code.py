import requests
import json
import time
import os

# 1. API Configuration

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
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PAGE_ID = "2f0eacc8-175a-805c-85b2-dca59899d3d8"

# 2. 파일 경로 매칭 (사용자 VS Code 구조 반영)
file_map = {
    "2606": "gitp/DFS_백트래킹/2606dfs그래프노드연결.py",
    "2667": "gitp/DFS_백트래킹/2667dfs백트래킹 핵심.py",
    "2644": "gitp/DFS_백트래킹/2644dfs에서의 실패하고 돌아올때 중복개수 방지.py",
    "7569": "gitp/BFS/75693차원 bfs 큐이용.py",
    "1697": "gitp/BFS/1697그래프 시간초과나서 안쓰는bfs.py",
    "5014": "gitp/BFS/5014그래프 안쓰는 bfs.py",
    "2468": "gitp/BFS/2468델타응용 bfs.py",
    "1926": "gitp/BFS/1926델타응용 bfs2.py"
}

def get_local_code(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    return None

def restore_notion():
    print("--- 🚀 VS Code 원본 코드 복구 시작 ---")
    
    # 노션 페이지 블록 목록 가져오기
    res = requests.get(f"https://api.notion.com/v1/blocks/{PAGE_ID}/children", headers=HEADERS)
    blocks = res.json().get('results', [])
    
    for prob_id, file_path in file_map.items():
        original_code = get_local_code(file_path)
        if not original_code:
            print(f"⚠️ Skip: {prob_id} 파일을 찾을 수 없습니다.")
            continue
            
        # 해당 문제의 Heading 블록 찾기
        for idx, block in enumerate(blocks):
            if block['type'] == 'heading_2':
                text = block['heading_2']['rich_text'][0]['plain_text']
                if prob_id in text:
                    # 바로 다음 코드 블록 업데이트
                    for next_idx in range(idx+1, idx+5):
                        if next_idx < len(blocks) and blocks[next_idx]['type'] == 'code':
                            code_id = blocks[next_idx]['id']
                            requests.patch(f"https://api.notion.com/v1/blocks/{code_id}", headers=HEADERS, json={
                                "code": {"rich_text": [{"type": "text", "text": {"content": original_code}}]}
                            })
                            print(f"✅ Success: BJ {prob_id} 원본 복구 완료")
                            break
                    break
    print("--- ✨ 모든 원본 코드 동기화 완료 ---")

if __name__ == "__main__":
    restore_notion()
