import requests
import os
import json
from pathlib import Path

def get_token():
    # Try reading from .env.notion or notion_automation/.env.notion
    paths = [
        Path(".env.notion"),
        Path("notion_automation/.env.notion"),
        Path("../../.env.notion")
    ]
    for p in paths:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == "NOTION_TOKEN":
                        return v.strip().strip('"').strip("'")
    return os.getenv("NOTION_TOKEN")

TOKEN = get_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def list_pages():
    if not TOKEN:
        print("❌ NOTION_TOKEN을 찾을 수 없습니다.")
        return []

    url = "https://api.notion.com/v1/search"
    payload = {
        "sort": {
            "direction": "descending",
            "timestamp": "last_edited_time"
        }
    }
    
    all_pages = []
    has_more = True
    next_cursor = None
    
    while has_more:
        if next_cursor:
            payload["start_cursor"] = next_cursor
            
        response = requests.post(url, json=payload, headers=HEADERS)
        if response.status_code != 200:
            print(f"❌ 에러 발생: {response.status_code}")
            print(response.text)
            break
            
        data = response.json()
        for result in data.get("results", []):
            page_id = result.get("id")
            obj_type = result.get("object")
            
            title = "제목 없음"
            if obj_type == "page":
                properties = result.get("properties", {})
                for prop_name, prop in properties.items():
                    if prop.get("type") == "title":
                        title_list = prop.get("title", [])
                        if title_list:
                            title = title_list[0].get("plain_text", "제목 없음")
                        break
            elif obj_type == "database":
                title_list = result.get("title", [])
                if title_list:
                    title = title_list[0].get("plain_text", "데이터베이스 제목 없음")
            
            all_pages.append({"id": page_id, "title": title, "type": obj_type})
            
        has_more = data.get("has_more")
        next_cursor = data.get("next_cursor")
        
    return all_pages

if __name__ == "__main__":
    pages = list_pages()
    if pages:
        with open("notion_pages_list.json", "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False, indent=2)
        # Print only the relevant one for algorithm
        for p in pages:
            if "삼성 A형" in p['title'] or "Algorithm" in p['title']:
                print(f"Target found: {p['title']} ({p['id']})")
