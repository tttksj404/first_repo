import requests
import os
import json
from dotenv import load_dotenv

# --- 인증 설정 ---
def get_token():
    load_dotenv()
    token = os.getenv("NOTION_TOKEN")
    if token: return token
    
    try:
        with open('.gemini/settings.json', 'r') as f:
            settings = json.load(f)
            token = settings.get("NOTION_TOKEN")
            if token: return token
    except: pass
    
    key_path = os.path.join(os.path.dirname(__file__), 'notion_key.txt')
    if os.path.exists(key_path):
        with open(key_path, 'r') as f:
            return f.read().strip()
    return None

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
    
    print("🔍 노션에서 페이지 목록을 불러오는 중...")
    
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
        print(f"\n✅ 총 {len(pages)}개의 페이지/데이터베이스를 찾았습니다.\n")
        print(f"{'유형':<10} | {'제목'}")
        print("-" * 50)
        for p in pages[:30]:
            print(f"{p['type']:<10} | {p['title']}")
        
        if len(pages) > 30:
            print(f"... 외 {len(pages)-30}개 더 있음")
        
        with open("notion_pages_list.json", "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False, indent=2)
        print(f"\n📂 전체 목록이 'notion_pages_list.json'에 저장되었습니다.")
