import requests
import json
import time

NOTION_TOKEN = "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"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def worker(pid, title, blocks):
    print(f"--- [UPDATING] {title} ---")
    url = f"https://api.notion.com/v1/blocks/{pid}/children"
    res_get = requests.get(url, headers=HEADERS)
    for b in res_get.json().get("results", []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.05)
    for i in range(0, len(blocks), 3):
        chunk = blocks[i:i+3]
        requests.patch(url, headers=HEADERS, json={"children": chunk})
        time.sleep(0.5)
    res_final = requests.get(url, headers=HEADERS)
    print(f"VERIFIED: {title} ({len(res_final.json().get('results', []))} blocks)")
    return True

# Data for batch 1
pop_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 06] 인구 이동 - BFS 기반 연합 형성"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "국경선을 열고 인구를 분배하는 시뮬레이션입니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔍 핵심 로직"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "연합: L <= abs(diff) <= R 만족 시 BFS로 묶음"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": "while moved: # repeat until no migration"}}]}},
    {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "💡"}, "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 매일 visited를 초기화하고 전수 조사하세요."}}]}}
]

fish_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 07] 낚시왕 - 속도 최적화 공식"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "상어의 빠른 속도를 처리하는 효율적인 위치 계산이 핵심입니다."}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": "speed %= (2 * (limit - 1))"}}]}},
    {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "💡"}, "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 이동 결과를 담을 새 맵을 사용해 상어 충돌을 관리하세요."}}]}}
]

tree_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 08] 나무 재테크 - 3D 자료구조"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "각 칸에 여러 나무가 있을 때의 성능 관리가 관건입니다."}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": "for age in trees[r][c]: if nut >= age: pass"}}]}},
    {"type": "callout", "callout": {"icon": {"type": "emoji", "emoji": "💡"}, "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 가을 번식 시 어린 나무를 리스트 앞에 넣으세요."}}]}}
]

worker("313eacc8-175a-817a-b91e-fc823a0ab988", "Pop", pop_blocks)
worker("313eacc8-175a-81cd-abb4-cd3ada7df20e", "Fish", fish_blocks)
worker("313eacc8-175a-8134-8838-f7c295125f8a", "Tree", tree_blocks)
