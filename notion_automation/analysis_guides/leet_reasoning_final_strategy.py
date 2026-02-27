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
PAGE_ID = "314eacc8175a819d985bee4f4d006c90"

def update():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    
    blocks = [
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "⚡ [전략] 추리논증: '키워드 스캔'과 '변수 마킹'"}}]}},
        {"type": "callout", "callout": {"rich_text": [{"text": {"content": "📢 핵심: 100% 이해보다 '필요 정보 발췌'에 집중. 키워드만으로 전체 맥락 파악 가능."}}], "icon": {"emoji": "🎯"}, "color": "purple_background"}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "1. 적극적 '변수 표시'"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "🔢 수치 마킹: 할인율, 정가, 인원 등 계산 변수에 즉시 표시."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "🚫 생략: 배경 설명은 머리로만 보고 표시를 아껴라. '조건'이 핵심이다."}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "2. 판단 도구: 논개매/강약매"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"text": {"content": "판단 도구 유무가 속도를 결정한다. 7일 내로 빠르게 1회독하여 '도구'만 건져라."}}]}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🛠️ 영역별 보완 전략"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "⚖️ 법률: 법학체계특강으로 뼈대 잡기."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "🧪 과학: EBS 수특 1.5배속으로 7일 컷. 고교 지식이면 충분."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "🔢 계산: 순열조합 교재로 노가다 시간 단축."}}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "💡 실전 팁: 경우의 수 축소"}}]}},
        {"type": "callout", "callout": {"rich_text": [{"text": {"content": "대우 활용: 'A면 B다' (경우의 수 많음) -> '~B면 ~A다' (경우의 수 1개로 축소)"}}], "icon": {"emoji": "⚡"}, "color": "blue_background"}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "🎓 학생 가이드: 배경지식보다 '기출 반복을 통한 체득'이 항상 우선입니다."}, "annotations": {"bold": True}}]}}
    ]

    print("--- DEPLOYING REASONING UPDATES ---")
    res = requests.patch(url, headers=HEADERS, json={"children": blocks})
    if res.status_code == 200:
        print("SUCCESS: 2025/2026 Trends updated in Reasoning Masterbook.")
    else:
        print(f"FAILED: {res.text}")

if __name__ == "__main__":
    update()
