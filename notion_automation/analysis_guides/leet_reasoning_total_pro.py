import requests
import json


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
PAGE_ID = "314eacc8175a819d985bee4f4d006c90"

def update():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    
    blocks = [
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "💎 2025-2026 통합 분석: 추리논증 140+ 달성을 위한 절대 역량과 훈련법"}}]}},
        {
            "type": "callout",
            "callout": {
                "rich_text": [{"text": {"content": "📢 총평: 추리논증은 120분 동안 40문제를 푸는 '두뇌 마라톤'이다. 1문제당 평균 3분 컷을 위해선 '지식'이 아닌 '정보 처리 알고리즘'이 뇌에 탑재되어야 한다."}}],
                "icon": {"emoji": "🧠"}, "color": "purple_background"
            }
        },
        
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "역량 1. 복합 규범 및 메커니즘의 '조건부 시뮬레이션'"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 근거: 25년 상속/이혼 규정(7번), 호르몬 투과(40번) / 26년 튜링기계, DMN 모델."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 기술: 텍스트로 주어지는 '예외의 예외(다만, ~의 경우는 제외한다)'를 코딩의 중첩 if-else 문처럼 구조화하여 실제 사례(Case)에 기계적으로 대입하는 능력."}}]}},

        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "역량 2. 논증(강화/약화)의 타격점 정밀 조준"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 근거: 25년 실험 설계(28, 29번), 위선자 규정(15번) / 26년 인과관계 및 도구변수."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 기술: 선지의 새로운 정보가 주장의 '전제'를 치는지, '인과 연결고리(통제되지 않은 제3의 변인)'를 치는지 1초 만에 파악하는 능력. (교락 효과 판단력)"}}]}},

        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "역량 3. 수리/논리 퍼즐의 '경우의 수 압축력'"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "📌 근거: 25년 죄수 구금일 퍼즐(33번), 변호사 배정(35번), 토지 면적 환산(12번)."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "✅ 기술: 무식한 노가다(Brute-force)를 버리고, 대우 명제나 '가장 제약이 심한 조건(확정값)'부터 채워 넣어 경우의 수를 단박에 1~2개로 압축하는 사냥개 작전."}}]}},

        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🏋️ 평소 실전 연습 방법 (120분 40문항 체화)"}}]}},
        
        {"type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "1. '기계적 변수 마킹' 훈련"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "문제를 읽을 때 숫자, 비율, 시점(2023년 vs 2024년), 주체(갑 vs 을)에 무조건 기호를 치세요. 뇌의 램(RAM)을 비우고 하드디스크(시험지)에 저장해야 계산 실수가 사라집니다."}}]}},

        {"type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "2. '10초 세모'와 '버리기' 전략 (Time Management)"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "언어이해가 70분에 30문제라면, 추리논증은 120분에 40문제입니다. 1문제당 평균 3분. 계산이 꼬이거나 논리가 붕 뜨는 선지에서 10초 이상 멈칫했다면 과감히 '세모' 치고 넘어가세요. 뒤에 더 쉬운 정답이 기다리고 있습니다."}}]}},

        {"type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "3. 논리 도구(논개매/강약매)의 단기 체화"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "강화약화매뉴얼과 논리개념매뉴얼을 5~7일 만에 빠르게 1회독하세요. 완벽한 이해가 아니라, 헷갈릴 때 꺼내 쓸 '무기(대우, 인과 판단 공식 등)'를 A4 한 장에 요약하여 매 시험 전 뇌에 각인시키는 것이 목적입니다."}}]}},

        {"type": "callout", "callout": {
            "rich_text": [{"text": {"content": "💡 SSAFY 연계 팁: 추리논증의 법학/과학 지문은 마치 낯선 프로그래밍 언어의 공식 문서를 읽는 것과 같습니다. 배경지식이 없어도 문서(지문)에 적힌 Syntax(규칙)만 정확히 대입하면 답이 나옵니다. 쫄지 마세요!"}}],
            "icon": {"emoji": "🔥"}, "color": "green_background"
        }}
    ]

    print("--- DEPLOYING REASONING TOTAL COMPETENCY UPDATES ---")
    res = requests.patch(url, headers=HEADERS, json={"children": blocks})
    if res.status_code == 200:
        print("SUCCESS: 2025-2026 Integrated Reasoning Strategy added to Notion.")
    else:
        print(f"FAILED: {res.text}")

if __name__ == "__main__":
    update()
