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

# 2. High-Density LEET Dashboard Blueprint
blueprint = {
    "LEET_DASHBOARD": {
        "title": "🏆 [2026] LEET 140+ 합격 사수: SSAFY 병행 대시보드",
        "blocks": [
            {
                "type": "callout",
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": "💡 전략: SSAFY 교육 중엔 '논리적 사고'를 훈련하고, 저녁엔 '기출의 필연성'을 분석한다.\n🚫 원칙: 23:00 취침 엄수. 수면 부족은 추론 능력의 적이다."}}],
                    "icon": {"type": "emoji", "emoji": "🚨"},
                    "color": "red_background"
                }
            },
            {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "⏰ 데일리 루틴 (수행 체크)"}}]}},
            {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "🌅 08:30 - 09:00 | Morning 예열: 언어이해 1지문 (점수보다 리듬)"}}], "checked": False}},
            {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "🏢 09:00 - 18:00 | SSAFY 교육: 알고리즘 로직 = 추리논증 연계 사고"}}], "checked": False}},
            {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "🍴 13:10 - 13:45 | Lunch 틈새: 추리 퀴즈 3~5개 or 오답 재독해"}}], "checked": False}},
            {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "🔥 20:15 - 23:00 | Night 집중(화,수,목): 기출 분석 메인 (언어2+추리15)"}}], "checked": False}},
            {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "📚 20:40 - 23:00 | Night 복습(월,금): 스터디 정리 및 취약 파트 보충"}}], "checked": False}},
            {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "💤 23:00 - 07:00 | 수면 및 회복: 7시간 이상 숙면 (기억 저장소 가동)"}}], "checked": False}},
            {"type": "divider", "divider": {}},
            {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "🔍 오늘의 기출 분석 & 논리 피드백"}}]}},
            {
                "type": "callout",
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": "아래에 [문제번호 / 나의 오답 논리 / 정답의 근거]를 작성하세요.\n작성 완료 후 저에게 분석을 요청하면, 'AI 접근 가이드'를 덧붙여 드립니다."}}],
                    "icon": {"type": "emoji", "emoji": "✍️"},
                    "color": "gray_background"
                }
            },
            {"type": "divider", "divider": {}},
            {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "📅 (여기에 오늘의 날짜와 분석 내용을 입력하세요...)"}, "annotations": {"italic": True}}]}}
        ]
    }
}

def worker(pid, data):
    print(f"--- Processing {data['title']} ---")
    url = f"https://api.notion.com/v1/blocks/{pid}/children"
    
    # 1. Chunked Patch (Using the exact logic from two days ago)
    blocks = data["blocks"]
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        res = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if res.status_code != 200:
            print(f"FAILED on chunk {i}: {res.text}")
            return False
        print(f"Chunk {i//3 + 1} deployed.")
        time.sleep(1) # 휴식 기법 적용
    
    print(f"VERIFIED: {data['title']} update complete.")
    return True

def create_page(parent_id, title):
    url = "https://api.notion.com/v1/pages"
    data = {
        "parent": {"page_id": parent_id},
        "icon": {"emoji": "🎓"},
        "cover": {"type": "external", "external": {"url": "https://images.unsplash.com/photo-1456513080510-7bf3a84b82f8?auto=format&fit=crop&w=1350&q=80"}},
        "properties": {
            "title": {"title": [{"text": {"content": title}}] }
        }
    }
    res = requests.post(url, headers=HEADERS, json=data)
    if res.status_code == 200:
        return res.json()['id']
    else:
        print(f"Page creation failed: {res.text}")
        return None

if __name__ == "__main__":
    PARENT_ID = "231eacc8175a80b6b30be061e8f5a3c5"
    
    # Create the page first
    new_pid = create_page(PARENT_ID, blueprint["LEET_DASHBOARD"]["title"])
    
    if new_pid:
        # Deploy blocks using the worker logic
        if worker(new_pid, blueprint["LEET_DASHBOARD"]):
            print(f"Successfully created LEET Dashboard: https://www.notion.so/{new_pid.replace('-', '')}")
