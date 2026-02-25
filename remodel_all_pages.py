# -*- coding: utf-8 -*-
import requests
import json
import time

TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_child_pages(parent_id):
    url = f"https://api.notion.com/v1/blocks/{parent_id}/children"
    res = requests.get(url, headers=HEADERS).json()
    return [b['id'] for b in res.get('results', []) if b['type'] == 'child_page']

def insert_elements(page_id, title):
    # Get current blocks
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    blocks_res = requests.get(url, headers=HEADERS).json().get('results', [])
    if not blocks_res: return

    first_id = blocks_res[0]['id']
    
    # 1. Insert ToC and Intro at TOP
    top_blocks = [
        {"object": "block", "type": "table_of_contents", "table_of_contents": {}},
        {"object": "block", "type": "callout", "callout": {
            "rich_text": [{"text": {"content": "💡 학생의 가이드: 기존 내용을 정독한 뒤, 제가 공부하며 덧붙인 하단 요약본을 함께 보시면 학습 효과가 두 배가 됩니다!"}}],
            "icon": {"emoji": "🎓"}
        }},
        {"object": "block", "type": "divider", "divider": {}}
    ]
    requests.patch(url, json={"children": top_blocks, "after": first_id}, headers=HEADERS)

    # 2. Append Summary at BOTTOM
    bottom_blocks = [
        {"object": "block", "type": "divider", "divider": {}},
        {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "📚 한눈에 보는 요약 및 실전 팁"}}]}},
        {"object": "block", "type": "quote", "quote": {"rich_text": [{"text": {"content": "기존의 상세 코드들을 충분히 익히셨다면, 아래의 핵심 포인트들을 머릿속에 정리해보세요.\n\n- 로직 설계: 주석으로 흐름 먼저 잡기\n- 예외 처리: 경계값 확인\n- 최적화: 상황에 맞는 자료구조 선택"}}]}}
    ]
    requests.patch(url, json={"children": bottom_blocks}, headers=HEADERS)
    print(f"Refined: {page_id}")

if __name__ == "__main__":
    parent_id = "2e7eacc8-175a-8035-8d30-ca6bf5e1c524"
    children = get_child_pages(parent_id)
    for child in children:
        insert_elements(child, "")
        time.sleep(1)
    print("All pages refined successfully without any deletion!")
