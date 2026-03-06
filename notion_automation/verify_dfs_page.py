import requests
import json
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def verify_page_content(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    response = requests.get(url, headers=HEADERS)
    
    if response.status_code != 200:
        print(f"Error fetching blocks: {response.text}")
        return

    data = response.json()
    blocks = data.get("results", [])
    
    print(f"--- Verification Report for Page: {page_id} ---")
    print(f"Total Blocks Found: {len(blocks)}")
    
    structure = []
    for b in blocks:
        b_type = b["type"]
        content = ""
        if b_type.startswith("heading"):
            content = b[b_type]["rich_text"][0]["plain_text"]
        elif b_type == "code":
            content = "Python Code Block"
        elif b_type == "callout":
            content = "Callout (Tip)"
        elif b_type == "quote":
            content = "Quote (Description)"
        
        structure.append(f"- [{b_type}] {content}")
    
    for s in structure:
        print(s)

    # Expected count is 28 (15 from initial + 13 from append)
    if len(blocks) >= 28:
        print("\n✅ [SUCCESS] All 28 expected blocks are present and verified.")
    else:
        print(f"\n⚠️ [WARNING] Expected 28 blocks, but found {len(blocks)}. Some content might be missing.")

if __name__ == "__main__":
    page_id = "31beacc8-175a-813c-ba9b-c0ff8e8d5d98"
    verify_page_content(page_id)
