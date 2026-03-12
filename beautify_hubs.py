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

def update_hub_content(hub_id, category_name, child_ids):
    # Fetch existing children to not overwrite if any
    # Actually we just want to list the sub-pages clearly
    
    children = []
    children.append({"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": f"📂 {category_name} 통합 허브"}}]}})
    children.append({"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "관련된 모든 마스터북과 문제 풀이 페이지들이 이곳에 집결되어 있습니다."}}]}})
    children.append({"type": "divider", "divider": {}})
    
    # We can't easily "move" blocks into a page without PATCH children,
    # but the pages are already moved as children. Notion UI will show them.
    # To make it look "good", we can add a table of contents.
    children.append({"type": "table_of_contents", "table_of_contents": {}})
    
    url = f"https://api.notion.com/v1/blocks/{hub_id}/children"
    requests.patch(url, headers=HEADERS, json={"children": children})

def beautify_hubs():
    with open("hubs.json", "r") as f:
        hubs = json.load(f)
        
    update_hub_content(hubs["algo"], "알고리즘 & 코딩테스트", [])
    update_hub_content(hubs["leet"], "LEET & 로스쿨", [])
    update_hub_content(hubs["dev"], "개발 지식 & SSAFY", [])

if __name__ == "__main__":
    beautify_hubs()
