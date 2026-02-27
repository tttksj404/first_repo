import requests
import json
import time

# 1. API 설정

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

def get_block_children(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    response = requests.get(url, headers=HEADERS)
    return response.json().get('results', [])

def append_feedback(block_id, user_logic):
    """
    사용자의 오답 논리를 분석하여 하단에 정석 접근법을 삽입합니다.
    (실제 구현 시에는 여기서 LLM API를 호출하거나 정해진 논리 가이드를 적용할 수 있습니다.)
    """
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    
    # 📝 [AI 가이드 샘플] - 실제 상황에 맞춰 유동적으로 생성되도록 설정 가능
    ai_feedback_content = f"🔍 [AI 논리 교정]
- 사용자의 논리: '{user_logic[:30]}...'
- LEET 접근 핵심: 본문에 근거가 없는 추론은 지양해야 합니다. '필연적 도출'인지 '가능성'인지를 엄격히 구분하세요.
- 향후 전략: 선지 검토 시 본문의 '단서어(다만, 그러나, 특히)'에 형광펜 표시 후 대조할 것."

    payload = {
        "children": [
            {"object": "block", "type": "divider", "divider": {}},
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"text": {"content": ai_feedback_content}}],
                    "icon": {"emoji": "💡"},
                    "color": "blue_background"
                }
            }
        ]
    }
    requests.patch(url, headers=HEADERS, json=payload)

def sync_leet_progress(page_id):
    print(f"🕵️ LEET 학습 상태 점검 중...")
    blocks = get_block_children(page_id)
    
    for block in blocks:
        # 1. 할 일(To-do) 블록이고 완료(Checked)된 경우 확인
        if block['type'] == 'to_do':
            is_checked = block['to_do']['checked']
            text_content = block['to_do']['rich_text'][0]['plain_text'] if block['to_do']['rich_text'] else ""
            
            # 2. 완료되었는데 아직 피드백이 달리지 않은 항목 찾기
            # (여기서는 간단히 텍스트 내용을 기반으로 하거나, 하위 블록 존재 여부로 판단)
            if is_checked and "완료" not in text_content: # 예시 조건
                print(f"✅ 완료된 항목 발견: {text_content}")
                
                # 3. 해당 항목 아래에 AI 피드백 삽입
                append_feedback(block['id'], text_content)
                
                # 4. 피드백 완료 표시 (무한 루프 방지용)
                # (실제로는 속성 변경이나 특정 텍스트 추가 등을 사용)

if __name__ == "__main__":
    # 마스터 플랜 페이지 ID
    LEET_PAGE_ID = "6159c3d2e2734a1796be57f208191983" 
    sync_leet_progress(LEET_PAGE_ID)
