import requests
import json
import time
import os

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

PARENT_PAGE_ID = "314eacc8-175a-817c-8fa6-c89fd1e36a66"

plan_data = {
    "children": [
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📅 [LEET 140+ Target] 7월 고득점 필승 로드맵 (March Start)"}}]}},
        {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "🚀"}, "rich_text": [{"type": "text", "text": {"content": "SSAFY 교육(09-18)과 병행하며 140점을 달성하기 위한 극한의 효율성 전략입니다. '양보다 질', '암기보다 논리 구조의 체득'에 집중합니다."}}]}},
        
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "1. 월별 마스터 플랜 (로드맵)"}}]}},
        
        {"type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": "📍 [3~4월] 기출 해부 및 논리 엔진 구축 (The Siege)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "중점: 2017~2025학년도(최신 9개년) 기출 전수 분석."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "방법: 문제를 푼 후, 정답 선지가 본문의 어떤 [[단어 질감]]이나 [[범주화]]에 근거했는지 옵시디언에 매핑."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "목표: 1,500개의 옵시디언 미아 링크 중 핵심 300개 이상을 기출 사례로 채우기."}}]}},

        {"type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": "📍 [5월] 논리적 확장 및 고전 기출 정복 (The Expansion)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "중점: 2009~2016학년도 기출 분석 및 유형별 정교화."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "방법: 최신 기출과 고전 기출의 논리적 [[공차관계]] 분석. '오답 함정 데이터베이스' 구축."}}]}},

        {"type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": "📍 [6월] 고난도 배경지식 융합 및 약점 타격 (The Peak)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "중점: PDF 보물 창고의 학술 논문 독해 + 법학/경제 고난도 리트릿."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "방법: [[데이터 철학]], [[양자역학]], [[비례의 원칙]] 등 킬러 제재의 심화 논리 체득."}}]}},

        {"type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": "📍 [7월] 최종 시뮬레이션 및 마인드 세팅 (The Hunt)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "중점: 주 2회 풀셋 모의고사 + 오답 행동 강령 복기."}}]}},

        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "2. [SSAFY 병행] 데일리 루틴 (Daily Routine)"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "SSAFY 교육 시간(09:00-18:00)을 상수로 두고, 가용 시간을 LEET에 몰입 투입합니다."}}]}},
        {"type": "table", "table": {"table_width": 2, "has_column_header": True, "has_row_header": False, "children": [
            {"type": "table_row", "table_row": {"cells": [[{"type": "text", "text": {"content": "시간"}}], [{"type": "text", "text": {"content": "학습 내용"}}]]}},
            {"type": "table_row", "table_row": {"cells": [[{"type": "text", "text": {"content": "07:00 - 08:30"}}], [{"type": "text", "text": {"content": "🌅 Morning: 언어이해 2지문 + 범주화 분석"}}]]}},
            {"type": "table_row", "table_row": {"cells": [[{"type": "text", "text": {"content": "09:00 - 18:00"}}], [{"type": "text", "text": {"content": "🏢 SSAFY: 쉬는 시간 옵시디언 1개 정독 (10분)"}}]]}},
            {"type": "table_row", "table_row": {"cells": [[{"type": "text", "text": {"content": "19:30 - 21:30"}}], [{"type": "text", "text": {"content": "🌙 Night: 추리논증 10-15문항 집중 풀이"}}]]}},
            {"type": "table_row", "table_row": {"cells": [[{"type": "text", "text": {"content": "21:30 - 22:30"}}], [{"type": "text", "text": {"content": "📝 Analysis: 오답 복기 및 옵시디언 지식 확장"}}]]}}
        ]}},

        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "3. 140점 달성 여부 객관적 진단"}}]}},
        {"type": "toggle", "toggle": {"rich_text": [{"type": "text", "text": {"content": "현실적 도달 가능성 분석 (클릭)"}}], "children": [
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "장점: 이미 120개 이상의 '5배 심화' 배경지식 파일이 구축되어 있어 독해 속도에서 압도적 우위 점함."}}]}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "과제: SSAFY의 강도 높은 일정을 이겨낼 '체력'과 '매일 4시간'의 순공 시간 확보가 관건."}}]}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "결론: 3월부터 기출 분석을 시작하여 '이론-실전'을 즉시 통합한다면 140점 달성 충분히 가능."}}]}}
        ]}}
    ]
}

def create_page():
    url = f"https://api.notion.com/v1/blocks/{PARENT_PAGE_ID}/children"
    res = requests.patch(url, headers=HEADERS, json=plan_data)
    if res.status_code == 200:
        print("✅ Notion에 LEET 140+ 마스터 플랜 주입 성공!")
    else:
        print(f"❌ 실패: {res.text}")

if __name__ == '__main__':
    create_page()
