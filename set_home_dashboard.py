import requests
import json
import os
import sys

sys.path.append(os.getcwd())
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def rename_page(page_id, new_title):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "title": [{"text": {"content": new_title}}]
        }
    }
    resp = requests.patch(url, headers=HEADERS, json=payload)
    return resp.status_code == 200

def get_blocks(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    resp = requests.get(url, headers=HEADERS)
    return resp.json().get("results", []) if resp.status_code == 200 else []

def clear_page(page_id):
    blocks = get_blocks(page_id)
    for b in blocks:
        url = f"https://api.notion.com/v1/blocks/{b['id']}"
        requests.delete(url, headers=HEADERS)

def setup_dashboard(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    children = [
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🏠 메인 대시보드 (Total Control Panel)"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "이곳은 모든 학습 및 프로젝트 데이터의 관제 센터입니다. 아래 카테고리를 통해 각 허브로 이동하세요."}}]}},
        {"type": "divider", "divider": {}},
        {
            "type": "column_list",
            "column_list": {
                "children": [
                    {
                        "type": "column",
                        "column": {
                            "children": [
                                {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "💻 알고리즘 & 코딩테스트"}}]}},
                                {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "삼성 A형, IM 대비 및 백준 문제 풀이"}}]}},
                                # Link to Algo Hub (manually find ID later or pass it)
                            ]
                        }
                    },
                    {
                        "type": "column",
                        "column": {
                            "children": [
                                {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🏛️ LEET & 로스쿨"}}]}},
                                {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "추리논증, 언어이해 및 데일리 루틴"}}]}}
                            ]
                        }
                    }
                ]
            }
        },
        {"type": "divider", "divider": {}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "📚 개발 지식 & SSAFY"}}]}}
    ]
    requests.patch(url, headers=HEADERS, json={"children": children})

if __name__ == "__main__":
    # Existing root page: 스터디 로드맵
    home_id = "231eacc8-175a-80b6-b30b-e061e8f5a3c5"
    
    print("Renaming root to '🏠 HOME'...")
    rename_page(home_id, "🏠 HOME (메인 대시보드)")
    
    print("Clearing and setting up dashboard content...")
    # Optionally clear, but maybe better to just append at the top. 
    # Let's append for safety since user said "don't delete original if not needed"
    # But here they want a clean Home.
    setup_dashboard(home_id)
    
    print("Dashboard setup on Home page completed.")
