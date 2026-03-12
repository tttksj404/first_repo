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

def create_dashboard():
    # 1. Create Main Dashboard
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"workspace": True},
        "properties": {
            "title": [{"text": {"content": "🏠 메인 대시보드 (Total Control Panel)"}}]
        },
        "children": [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"text": {"content": "이곳은 모든 학습 및 프로젝트 데이터의 관제 센터입니다. 아래 카테고리를 통해 각 허브로 이동하세요."}}]
                }
            },
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
                                    {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "삼성 A형, IM 대비 및 백준 문제 풀이"}}]}}
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
            {
                "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "📚 개발 지식 & SSAFY"}}]}}
        ]
    }
    resp = requests.post(url, headers=HEADERS, json=payload)
    if resp.status_code == 200:
        main_page = resp.json()
        print(f"Created Main Dashboard: {main_page['id']}")
        return main_page["id"]
    else:
        print(f"Failed: {resp.text}")
        return None

def create_hub(title, parent_id, emoji):
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"page_id": parent_id},
        "icon": {"emoji": emoji},
        "properties": {
            "title": [{"text": {"content": title}}]
        }
    }
    resp = requests.post(url, headers=HEADERS, json=payload)
    return resp.json()["id"] if resp.status_code == 200 else None

if __name__ == "__main__":
    dash_id = create_dashboard()
    if dash_id:
        algo_hub = create_hub("💻 알고리즘 Hub", dash_id, "💻")
        leet_hub = create_hub("🏛️ LEET Hub", dash_id, "🏛️")
        dev_hub = create_hub("📚 개발 & SSAFY Hub", dash_id, "📚")
        
        print(f"Algo Hub: {algo_hub}")
        print(f"LEET Hub: {leet_hub}")
        print(f"Dev Hub: {dev_hub}")
        
        # Save mapping
        with open("hubs.json", "w") as f:
            json.dump({
                "main": dash_id,
                "algo": algo_hub,
                "leet": leet_hub,
                "dev": dev_hub
            }, f)
