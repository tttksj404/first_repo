import requests
import json
import os
import time

TOKEN = os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PARENT_PAGE_ID = "303eacc8-175a-80a3-9154-f7a7acee7c80" # 코테 대비

def clean_block(block):
    # Strip Notion-internal fields so the block can be reused in a POST/PATCH request
    b_type = block.get("type")
    if not b_type: return None
    
    # Get the inner content for this block type
    inner = block.get(b_type, {})
    
    # Strictly filter the inner object
    # For common types like paragraph, headings, bulleted_list_item, etc., 
    # we only want rich_text and maybe color/is_toggleable.
    cleaned_inner = {}
    allowed_inner_keys = ["rich_text", "checked", "language", "color", "is_toggleable", "icon"]
    
    for k in allowed_inner_keys:
        if k in inner:
            val = inner[k]
            # Further clean rich_text if it's there
            if k == "rich_text" and isinstance(val, list):
                new_rt = []
                for rt in val:
                    content = rt.get("text", {}).get("content", "")
                    # Split content if it's too long
                    chunk_size = 1900
                    for start in range(0, len(content), chunk_size):
                        sub_content = content[start : start + chunk_size]
                        rt_cleaned = {
                            "type": "text",
                            "text": {"content": sub_content},
                            "annotations": rt.get("annotations", {})
                        }
                        # Preserve link if it exists (only on the first chunk for simplicity, 
                        # or all if it's a long link - but links aren't usually 2000+ chars)
                        link = rt.get("text", {}).get("link")
                        if link:
                            rt_cleaned["text"]["link"] = {"url": link.get("url")} if isinstance(link, dict) and "url" in link else None
                        
                        new_rt.append(rt_cleaned)
                cleaned_inner[k] = new_rt
            else:
                cleaned_inner[k] = val
    
    return {
        "object": "block",
        "type": b_type,
        b_type: cleaned_inner
    }

def api_request(method, path, payload=None):
    url = f"https://api.notion.com/v1{path}"
    for attempt in range(1, 6):
        try:
            response = requests.request(method, url, headers=HEADERS, json=payload, timeout=30)
            if response.status_code == 429:
                time.sleep(2**attempt)
                continue
            if response.status_code != 200:
                print(f"❌ API Error {response.status_code}: {response.text}")
                # Log the payload that caused the error for debugging
                with open("error_payload.json", "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if attempt == 5: raise e
            time.sleep(2)

def create_page(title, parent_id):
    payload = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {"title": [{"text": {"content": title}}]}
        },
        "icon": {"type": "emoji", "emoji": "🏆"}
    }
    return api_request("POST", "/pages", payload)

def append_blocks(block_id, blocks):
    # Notion API has a limit of 100 blocks per request
    for i in range(0, len(blocks), 50):
        chunk = blocks[i:i+50]
        api_request("PATCH", f"/blocks/{block_id}/children", {"children": chunk})
        time.sleep(0.5)

def divider():
    return {"object": "block", "type": "divider", "divider": {}}

def heading(text, level=1):
    t = f"heading_{level}"
    return {
        "object": "block",
        "type": t,
        t: {"rich_text": [{"type": "text", "text": {"content": text}}]}
    }

def main():
    print("🚀 Consolidating Masterbook...")
    with open("notion_consolidation_data.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Create the Masterbook page
    new_page = create_page("🏆 [Master] 삼성 A형 알고리즘 백지코딩 마스터북", PARENT_PAGE_ID)
    master_id = new_page["id"]
    print(f"✅ Created Masterbook Page: {master_id}")

    final_blocks = []
    
    # 1. Introduction
    final_blocks.append(heading("💡 나의 약점 & 실전 핵심 포인트 (최우선 숙지)", level=1))
    
    # Merge Weak Points and IM Summary Brief
    for b in data["weak_points"]:
        cleaned = clean_block(b)
        if cleaned: final_blocks.append(cleaned)
    
    final_blocks.append(divider())
    final_blocks.append(heading("📘 [Level 1] 기초 이론 및 정석 템플릿", level=1))
    
    for b in data["codex_summary"]:
        cleaned = clean_block(b)
        if cleaned: final_blocks.append(cleaned)
        
    final_blocks.append(divider())
    final_blocks.append(heading("🔥 [Level 2] 백트래킹 & 응용 문제 풀이 전략", level=1))
    
    for b in data["backtracking_master"]:
        cleaned = clean_block(b)
        if cleaned: final_blocks.append(cleaned)

    # Note: Some blocks might be empty or problematic, filter them
    valid_blocks = [b for b in final_blocks if b]
    
    print(f"📦 Total blocks to append: {len(valid_blocks)}")
    append_blocks(master_id, valid_blocks)
    print("✅ Consolidation complete!")

if __name__ == "__main__":
    main()
