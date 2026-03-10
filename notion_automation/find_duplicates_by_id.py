import requests
import json
import time
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def list_all_pages():
    url = "https://api.notion.com/v1/search"
    payload = {
        "filter": {"property": "object", "value": "page"},
        "sort": {"direction": "descending", "timestamp": "last_edited_time"}
    }
    results = []
    has_more = True
    start_cursor = None
    
    while has_more:
        if start_cursor: payload["start_cursor"] = start_cursor
        res = requests.post(url, headers=HEADERS, json=payload)
        if res.status_code == 200:
            data = res.json()
            results.extend(data.get("results", []))
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")
        else:
            has_more = False
    return results

def main():
    pages = list_all_pages()
    grouped = {}
    for p in pages:
        title = "Untitled"
        props = p.get("properties", {})
        for k, v in props.items():
            if v.get("type") == "title":
                title_list = v.get("title", [])
                if title_list: title = title_list[0].get("plain_text", "Untitled")
                break
        
        # Try to find problem number in title
        import re
        match = re.search(r"\d{4,5}", title)
        problem_id = match.group(0) if match else "NoID"
        
        if problem_id not in grouped: grouped[problem_id] = []
        grouped[problem_id].append({"title": title, "id": p["id"]})
        
    print(json.dumps(grouped, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
