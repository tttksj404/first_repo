import requests
import json
import time


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
PAGE_ID = "314eacc8-175a-817c-8fa6-c89fd1e36a66"

def build():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    
    # Clean page first
    res_get = requests.get(url, headers=HEADERS).json()
    for b in res_get.get('results', []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.1)

    # High-density blocks with unicode safe strings
    content = [
        {"type": "table_of_contents", "table_of_contents": {}},
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🔍 Ⅰ. 스캐너 읽기 & 10초 세모 전략"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"text": {"content": "리트는 지능 시험이 아니라 '태도'의 시험이다. 100% 이해를 포기하고 정보의 위치만 마킹하는 스캐너가 되어라. 지문에 다녀와도 모르면 10초 안에 세모 치고 넘어가라."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "기계적 스캔: 말을 가장 빠르게 할 때의 속도로 눈을 굴려라. 문장 다시 읽기는 절대 금지."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "표시법: 주요 용어, 변화, 비교, 대립, 규칙에만 최소 마킹. 모르면 통으로 네모."}}]}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "📅 Ⅱ. 40일 4회독 기출 세뇌 플랜"}}]}},
        {"type": "callout", "callout": {"rich_text": [{"text": {"content": "대상: 2016~2026 (11년치) / 방식: 매일 1년치 / 총 4회 반복 (답이 외워져도 무관)"}}], "icon": {"emoji": "🔄"}}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "✅ Ⅲ. 데일리 체크리스트 (SSAFY 병행)"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🌅 08:30 | 아침 예열 (언어 1지문 7분 컷)"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🏢 09:00 | SSAFY 교육 (알고리즘 예외 조건 = 추리 단서 발췌)"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🍴 13:10 | 점심 틈새 (추리 퀴즈 3문항 or 오답 재독해)"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🔥 20:15 | 기출 세뇌 (1년치 풀 세트 전력 질주)"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "📝 22:30 | 오답 논리 리포트 (실수 분석 중심)"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "💤 23:00 | 7시간 숙면 사수 (뇌 정보 정리 시간)"}}]}},
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🧪 Ⅳ. 논리 피드백 연구소"}}]}},
        {"type": "callout", "callout": {"rich_text": [{"text": {"content": "아래에 [문제번호 / 나의 오답 논리 / 정답 근거]를 적으세요.
기록 후 저에게 '내 논리 분석해줘'라고 요청하면 피드백을 덧붙입니다."}}], "icon": {"emoji": "📝"}}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "여기에 오늘의 기록을 남겨주세요..."}, "annotations": {"italic": True}}]}}
    ]

    for i in range(0, len(content), 3):
        requests.patch(url, headers=HEADERS, json={"children": content[i:i+3]})
        time.sleep(0.5)
    print("SUCCESS: Full Rebuild Complete.")

if __name__ == "__main__":
    build()
