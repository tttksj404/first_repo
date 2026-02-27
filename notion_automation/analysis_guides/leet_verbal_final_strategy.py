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
# 언어이해 마스터북 페이지 ID
PAGE_ID = "314eacc8175a818a92dacd2d38cc4f4c"

def update_verbal_strategy():
    print("--- 📕 [언어이해] 필승 행동 강령 및 4회독 플랜 주입 중 ---")
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    
    # 초고밀도 전략 블록 정의 (제공해주신 텍스트 100% 반영)
    content = [
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "㊙️ [필승] LEET 언어이해 행동 강령: 스캐너 전략"}}]}},
        {
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": "⚠️ 리트의 본질: 고득점자도 시간 내에 100% 이해할 수 없도록 설계된 시험이다. '완벽한 이해'라는 강박을 버리는 순간 140점이 열린다."}}],
                "icon": {"emoji": "🚫"}, "color": "red_background"
            }
        },
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "1. '스캐너 읽기' (Scanner Reading)"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "지문 읽기의 1차 목표는 '이해'가 아니라 '정보의 위치 파악'이다. 이해와 고민은 문제를 풀 때 선지가 헷갈릴 때만 수행한다."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "🚫 절대 금지: 문장 다시 읽기, 읽으면서 멈춰서 생각하기."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "⚙️ 기계적 스캔: 말을 가장 빠르게 할 때의 속도로 토씨 하나 빠짐없이 눈으로 훑는다."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "📝 효율적 표시: 주요 용어, 변화, 비교, 대립, 규칙에만 표시. 이해 안 되면 통으로 네모 치고 전진."}}]}},
        
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "2. '선지 세모' (Triangle Strategy)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "⏳ 10초 룰: 지문을 확인해도 판단이 안 된다면 10초 이상 고민하지 말고 즉시 '세모' 치고 다음 선지로 이동."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "🎯 확신: 내가 고민하는 선지보다 더 명확한 답이 아래에 있을 확률이 매우 높다."}}]}},

        {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📅 [실천] 40일 완성: 기출 4회독 커리큘럼"}}]}},
        {"type": "callout", "callout": {
            "rich_text": [{"type": "text", "text": {"content": "기출 회독의 목적: 출제자의 사고방식과 판단 기준에 내 뇌를 '세뇌'시키는 과정이다. 답이 외워져도 상관없다."}}],
            "icon": {"emoji": "🧠"}, "color": "blue_background"
        }},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "🔄 범위: 2016~2026년도 (11년치) 매일 1년치 풀이."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "⏱️ 방식: 과목 시작 시 중간에 끊지 않기, 스톱워치 사용 (알람 X)."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "📄 교구: 실제 시험지 크기로 구입하여 현장감 극대화."}}]}},

        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "3. 혁신적 오답 노트 (30분 컷)"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "✂️ 틀린 문제/실수한 문제를 스크랩하여 5분간 전력 풀이."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "💡 요령 습득: 타인의 효율적 풀이법을 찾아 내 것으로 흡수."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "🚫 분석 지양: 지문이 선지 어디로 이어지는지 분석하는 '강사용 공부'는 시간 낭비다. 내 실수를 잡는 데만 집중."}}]}},
        {"type": "divider", "divider": {}}
    ]

    # 3개씩 쪼개서 전송 (안정성)
    for i in range(0, len(content), 3):
        chunk = content[i:i+3]
        requests.patch(url, headers=HEADERS, json={"children": chunk})
        time.sleep(0.8)
    
    print("✨ 언어이해 행동 강령 보강 완료!")

if __name__ == "__main__":
    update_verbal_strategy()
