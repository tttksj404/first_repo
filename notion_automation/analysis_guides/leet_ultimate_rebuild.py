import requests
import json
import time

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
PAGE_ID = "314eacc8175a817c8fa6c89fd1e36a66"

def update():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    
    # Pre-cleaning: Delete old blocks
    try:
        res_get = requests.get(url, headers=HEADERS)
        for block in res_get.json().get('results', [])[:20]:
            requests.delete(f"https://api.notion.com/v1/blocks/{block['id']}", headers=HEADERS)
            time.sleep(0.1)
    except: pass

    # Content with safe string handling
    content = [
        {"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": "[절대 원칙] 리트는 '지능'이 아니라 '세뇌'다.\n1. 이해하지 마라, 스캔하라.\n2. 고민하지 마라, 세모 쳐라 (10초 룰).\n3. 분석하지 마라, 기출을 뇌에 박아라."}}], "icon": {"emoji": "🚨"}, "color": "red_background"}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "📅 1단계: [3/2 ~ 4/10] 40일 4회독 뇌 세뇌 Sprint"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"text": {"content": "2016~2026 기출 무한 회독. 답이 외워져도 상관없다. 출제자의 사고 회로를 내 뇌에 복사하는 과정이다."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "평일 저녁: 20:15~23:00 기출 1세트 + 30분 오답 노트 (실수 교정 위주)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "주말 오전: 실제 시험지 크기로 전력 질주 (9시 시작)"}}]}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "⏰ SSAFY 최적화 필승 타임라인"}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🌅 08:30 - 09:00 | 스캐너 예열"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "언어 1지문. 정보 위치만 파악하며 7분 컷 연습."}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🏢 09:00 - 18:00 | 알고리즘 = 추리논증"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "코드의 Edge Case 분석 습관을 추리논증 단서 발췌에 대입."}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🔥 20:15 - 23:00 | 기출 세뇌"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "스캐너식 풀이 후 30분 오답 리포트. 23:00 취침 필수."}}]}},
        {"type": "divider", "divider": {}},
        {"type": "callout", "callout": {"rich_text": [{"text": {"content": "💡 Tip: 점수가 안 오르면 분석을 줄이고 속도를 높이세요. 찝찝함을 참는 자가 승리합니다."}}], "icon": {"emoji": "🚀"}, "color": "blue_background"}}
    ]

    print("--- DEPLOYING ULTIMATE WORKSPACE ---")
    for i in range(0, len(content), 3):
        chunk = content[i:i+3]
        requests.patch(url, headers=HEADERS, json={"children": chunk})
        time.sleep(0.8)
    print("SUCCESS: Link: https://www.notion.so/314eacc8175a817c8fa6c89fd1e36a66")

if __name__ == "__main__":
    update()
