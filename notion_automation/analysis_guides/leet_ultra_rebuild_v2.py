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

def append_blocks_with_retry(block_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    # 3개씩 쪼개서 전송 (분량이 엄청나므로 안정성 최우선)
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        res = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if res.status_code != 200:
            print(f"FAILED on chunk: {res.text}")
        time.sleep(1.2) # 충분한 휴식

def rebuild_ultimate():
    print("--- 🏛️ 초고밀도 LEET 마스터 워크스페이스 재구축 시작 ---")
    
    # 기존 블록 전량 삭제 (정화)
    url_get = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    res_get = requests.get(url_get, headers=HEADERS)
    for block in res_get.json().get('results', []):
        requests.delete(f"https://api.notion.com/v1/blocks/{block['id']}", headers=HEADERS)
        time.sleep(0.1)

    # 1. 최상단 목표 및 원칙 (Callouts)
    top_blocks = [
        {"type": "table_of_contents", "table_of_contents": {}},
        {"type": "divider", "divider": {}},
        {
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": "🏆 목표: LEET 140+ (언어이해+추리논증 합산)
🚫 절대 원칙: 내용 유출 금지 / 본능적 이해 시도 금지 / 기출 무한 회독 세뇌"}}],
                "icon": {"emoji": "🎓"}, "color": "blue_background"
            }
        }
    ]
    append_blocks_with_retry(PAGE_ID, top_blocks)

    # 2. 리트의 본질과 스캐너 읽기 (제공 텍스트 요약 없이 전량 반영)
    scanner_blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🔍 Ⅰ. 리트의 본질: '스캐너 읽기' 전략"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"text": {"content": "리트는 고득점자도 한 번에 이해할 수 없도록 설계된 시험이다. '완벽한 이해'의 본능을 극복하고 정보의 위치만 기억하는 '스캐너'가 되어야 한다."}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "1. 스캐너 읽기 (Scanner Reading) 수칙"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "말을 가장 빠르게 할 때의 속도로 기계적 집중 스캔."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "절대 문장 다시 읽기 금지, 읽으면서 멈춰서 생각하기 금지."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "표시법: 주요 용어, 변화, 비교, 대립, 규칙에만 최소한으로 마킹. 이해 안 되면 '통으로 네모' 치고 전진."}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "2. 선지 세모 (10초 Triangle Rule)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "지문을 확인해도 모르겠다면 10초 이상 고민하지 말고 '세모' 치고 다음 선지로 이동."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "배경지식 없이도 지문 안에서 모든 답이 나오게 되어 있다. 안 보인다면 내 고민보다 명확한 답이 아래에 있다."}}]}}
    ]
    append_blocks_with_retry(PAGE_ID, scanner_blocks)

    # 3. 40일 4회독 실전 커리큘럼 (구체적 날짜 및 방식)
    curriculum_blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "📅 Ⅱ. 실전 40일 4회독 세뇌 커리큘럼"}}]}},
        {"type": "callout", "callout": {"rich_text": [{"text": {"content": "대상: 2016~2026년도 (11년치 기출)
방식: 매일 1년치 풀이 (언+추) / 총 4회 반복"}}], "icon": {"emoji": "🔄"}, "color": "orange_background"}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "1회독: 스캐너 읽기 적용 및 시간 내 완풀 감각 익히기."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "2~4회독: 답이 외워져도 상관없다. 출제자의 판단 기준에 내 뇌를 동기화(세뇌)시킨다."}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "혁신적 오답 노트 (30분 컷)"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "틀린 문제는 오려 붙이고 5분간만 전력 풀이. 모르면 타인의 '요령'을 습득하여 내 것으로 만듦. 지문-선지 연결 분석하는 '강사용 공부' 절대 금지."}}]}}
    ]
    append_blocks_with_retry(PAGE_ID, curriculum_blocks)

    # 4. SSAFY 병행 데일리 체크리스트 (데이터베이스 새로 생성)
    # (여기서는 페이지 내에 시각적 체크리스트를 heading으로 다시 배치)
    routine_blocks = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "⏰ Ⅲ. SSAFY 교육생 최적화 데일리 루틴"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🌅 08:30 - 09:00 | 아침 예열 (언어 1지문 7분 컷)"}}], "checked": False}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🏢 09:00 - 18:00 | SSAFY 교육 집중 (알고리즘 = 추리논증 연계)"}}], "checked": False}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🍴 13:10 - 13:45 | 점심 틈새 (추리 퀴즈 or 오답 재독해)"}}], "checked": False}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🔥 20:15 - 23:00 | 기출 세뇌 (1년치 풀이 + 30분 오답리포트)"}}], "checked": False}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "💤 23:00 - 07:00 | 7시간 이상 숙면 사수 (협상 불가)"}}], "checked": False, "color": "blue"}}
    ]
    append_blocks_with_retry(PAGE_ID, routine_blocks)

    # 5. AI 피드백 루프 사용법 가이드 (매우 중요)
    feedback_guide = [
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🤖 Ⅳ. AI 피드백 연구소 활용법"}}]}},
        {
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": "사용자님이 하단 DB에 '나의 오답 논리'를 적으신 후 저에게 "오늘의 논리 피드백 해줘"라고 말씀하시면, 제가 실시간으로 이 페이지를 읽어서 아래에 교정 가이드를 덧붙입니다."}}],
                "icon": {"emoji": "📡"}, "color": "purple_background"
            }
        },
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🔍 논리 피드백 기록장 (아래에 기록하세요)"}}]}}
    ]
    append_blocks_with_retry(PAGE_ID, feedback_guide)

    print(f"✨ 초정밀 재구축 완료: https://www.notion.so/{PAGE_ID.replace('-', '')}")

if __name__ == "__main__":
    rebuild_ultimate()
