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
    if resp.status_code == 200:
        return resp.json()["id"]
    print(f"Hub creation failed for {title}: {resp.text}")
    return None

if __name__ == "__main__":
    # Use "스터디 로드맵" as temporary parent if workspace root is not allowed
    # OR better, use the existing root page "스터디 로드맵" (231eacc8-175a-80b6-b30b-e061e8f5a3c5)
    existing_root_id = "231eacc8-175a-80b6-b30b-e061e8f5a3c5"
    
    dash_id = create_hub("🏠 메인 대시보드", existing_root_id, "🏠")
    
    if dash_id:
        algo_hub = create_hub("💻 알고리즘 Hub", dash_id, "💻")
        leet_hub = create_hub("🏛️ LEET Hub", dash_id, "🏛️")
        dev_hub = create_hub("📚 개발 & SSAFY Hub", dash_id, "📚")
        
        print(f"Main Dashboard: {dash_id}")
        print(f"Algo Hub: {algo_hub}")
        print(f"LEET Hub: {leet_hub}")
        print(f"Dev Hub: {dev_hub}")
        
        with open("hubs.json", "w") as f:
            json.dump({
                "main": dash_id,
                "algo": algo_hub,
                "leet": leet_hub,
                "dev": dev_hub
            }, f)
