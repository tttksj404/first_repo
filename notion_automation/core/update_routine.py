import requests
import json
import time
import os
from datetime import datetime

def _get_notion_token():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(current_dir, 'notion_key.txt'),
        os.path.join(os.getcwd(), 'notion_automation', 'core', 'notion_key.txt')
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return f.read().strip()
    return os.getenv("NOTION_TOKEN")

NOTION_TOKEN = _get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

DATABASE_ID = "314eacc8-175a-8100-b638-fdfe053da235"

def create_daily_task_page():
    url = "https://api.notion.com/v1/pages"
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    new_page_data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": f"🔥 [LEET 140+] 3월 기출 해부 데일리 루틴 ({today_str})"}}]},
            "Date": {"date": {"start": today_str}},
            "SSAFY": {"select": {"name": "평일"}},
            "Tags": {"multi_select": [{"name": "공통"}]}
        },
        "children": [
            {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "🚀 오늘의 140+ 핵심 미션"}}]}},
            {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "🧠"}, "rich_text": [{"type": "text", "text": {"content": "모든 오답은 옵시디언 '5배 심화' 원칙에 따라 복기합니다. 단순 오답은 공부가 아닙니다. 사고의 교정만이 140점을 만듭니다."}}]}},
            
            {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🌅 Morning (07:00 - 08:30)"}}]}},
            {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "언어이해 최신 기출 2지문 풀이 (시간 엄수)"}}]}},
            {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "지문 내 [[단어 질감]] 및 [[핵심 범주화]] (+) / (-) 마킹 검토"}}]}},
            
            {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🏢 SSAFY Break (틈새 10분)"}}]}},
            {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "옵시디언 배경지식 1개 정독 및 5x 심화 업데이트"}}]}},
            
            {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🌙 Night (19:30 - 22:30)"}}]}},
            {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "추리논증 기출 15문항 (논리게임 & 법학 중심) 풀이"}}]}},
            {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "오답 문항 [[입증 책임]] 및 [[형식적 오류]] 역추적"}}]}},
            {"type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": "끊어진 옵시디언 링크 3개 복구 (기출 사례 주입)"}}]}},
            
            {"type": "divider", "divider": {}},
            {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "내일의 나를 위해 오늘의 오답 논리를 노션 '논리 피드백 연구소'에 한 문장으로 요약했는가?"}}]}}
        ]
    }
    
    res = requests.post(url, headers=HEADERS, json=new_page_data)
    if res.status_code == 200:
        print("✅ 데일리 루틴 체크리스트 생성 성공!")
    else:
        print(f"❌ 실패: {res.text}")

if __name__ == '__main__':
    create_daily_task_page()
