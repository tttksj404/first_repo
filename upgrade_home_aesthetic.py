import requests
import json
import os
import sys
import time

sys.path.append(os.getcwd())
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def delete_all_children(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        blocks = resp.json().get("results", [])
        for b in blocks:
            requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
            time.sleep(0.1)

def create_rich_text(text, bold=False, color="default", link=None):
    rt = {"type": "text", "text": {"content": text}}
    if link: rt["text"]["link"] = {"url": link}
    rt["annotations"] = {"bold": bold, "color": color}
    return [rt]

def update_home_aesthetic(home_id, hubs):
    delete_all_children(home_id)
    
    url = f"https://api.notion.com/v1/blocks/{home_id}/children"
    
    children = [
        # 1. Header & Nav
        {"type": "heading_1", "heading_1": {"rich_text": create_rich_text("🚀 PERSONAL MASTER DASHBOARD", bold=True)}},
        {"type": "callout", "callout": {
            "icon": {"emoji": "🏠"},
            "color": "gray_background",
            "rich_text": [
                {"type": "text", "text": {"content": "HOME"}, "annotations": {"bold": True}},
                {"type": "text", "text": {"content": "  |  "}},
                {"type": "text", "text": {"content": "💻 ALGO"}, "text": {"content": "💻 ALGO", "link": {"url": f"https://www.notion.so/{hubs['algo'].replace('-', '')}"}}},
                {"type": "text", "text": {"content": "  |  "}},
                {"type": "text", "text": {"content": "🏛️ LEET"}, "text": {"content": "🏛️ LEET", "link": {"url": f"https://www.notion.so/{hubs['leet'].replace('-', '')}"}}},
                {"type": "text", "text": {"content": "  |  "}},
                {"type": "text", "text": {"content": "📚 DEV"}, "text": {"content": "📚 DEV", "link": {"url": f"https://www.notion.so/{hubs['dev'].replace('-', '')}"}}}
            ]
        }},
        {"type": "divider", "divider": {}},
        
        # 2. 3-Column Layout
        {
            "type": "column_list",
            "column_list": {
                "children": [
                    {
                        "type": "column", # Column 1: Core Hubs
                        "column": {
                            "children": [
                                {"type": "heading_3", "heading_3": {"rich_text": create_rich_text("🔥 핵심 학습 허브", bold=True)}},
                                {"type": "callout", "callout": {
                                    "icon": {"emoji": "💻"},
                                    "color": "blue_background",
                                    "rich_text": create_rich_text("알고리즘 & 코테\n삼성 A형 집중 공략", bold=False)
                                }},
                                {"type": "callout", "callout": {
                                    "icon": {"emoji": "🏛️"},
                                    "color": "orange_background",
                                    "rich_text": create_rich_text("LEET & 로스쿨\n추리논증/언어이해", bold=False)
                                }}
                            ]
                        }
                    },
                    {
                        "type": "column", # Column 2: Today's Routine
                        "column": {
                            "children": [
                                {"type": "heading_3", "heading_3": {"rich_text": create_rich_text("📅 데일리 루틴", bold=True)}},
                                {"type": "to_do", "to_do": {"rich_text": create_rich_text("08:30 Morning 예열 (언어이해)"), "checked": False}},
                                {"type": "to_do", "to_do": {"rich_text": create_rich_text("09:00 SSAFY 교육 & 알고리즘"), "checked": False}},
                                {"type": "to_do", "to_do": {"rich_text": create_rich_text("20:15 Night 집중 학습"), "checked": False}}
                            ]
                        }
                    },
                    {
                        "type": "column", # Column 3: Quick Resources
                        "column": {
                            "children": [
                                {"type": "heading_3", "heading_3": {"rich_text": create_rich_text("🛠️ 퀵 리소스", bold=True)}},
                                {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": create_rich_text("AI 활용 가이드 (명령법)")}},
                                {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": create_rich_text("Python 문법 마스터북")}}
                            ]
                        }
                    }
                ]
            }
        },
        {"type": "divider", "divider": {}},
        
        # 3. Footer / Motivation
        {"type": "quote", "quote": {"rich_text": create_rich_text("매일의 꾸준함이 비범함을 만듭니다. 오늘도 화이팅! 💪", color="gray")}}
    ]
    
    requests.patch(url, headers=HEADERS, json={"children": children})

if __name__ == "__main__":
    # Actual IDs
    hubs = {
        "main": "231eacc8-175a-80b6-b30b-e061e8f5a3c5",
        "algo": "321eacc8-175a-81e1-adff-f68460b7221a",
        "leet": "321eacc8-175a-8118-b4be-dd94bda3e726",
        "dev": "321eacc8-175a-81b5-8b9c-f9e95b4b4567"
    }
    
    print("Upgrading Home aesthetics...")
    update_home_aesthetic(hubs["main"], hubs)
    print("Home dashboard upgraded.")
