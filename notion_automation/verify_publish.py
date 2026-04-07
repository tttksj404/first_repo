import requests
import os

NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
PAGE_ID = "325eacc8175a811d8237c7414ef471ea"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28"
}

def verify_notion_page(page_id):
    # Check Page
    url = f"https://api.notion.com/v1/pages/{page_id}"
    res = requests.get(url, headers=HEADERS)
    if res.status_code != 200:
        print(f"❌ Page check failed: {res.status_code}")
        return

    page_data = res.json()
    title = page_data.get("properties", {}).get("title", {}).get("title", [{}])[0].get("plain_text")
    print(f"✅ Page Title: {title}")

    # Check Blocks
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        blocks = res.json().get("results", [])
        print(f"✅ Total Blocks Found: {len(blocks)}")
        
        # Check first few blocks to verify content
        for i, block in enumerate(blocks[:10]):
            b_type = block.get("type")
            content = ""
            if b_type == "heading_1":
                content = block[b_type]["rich_text"][0]["plain_text"]
            elif b_type == "heading_3":
                content = block[b_type]["rich_text"][0]["plain_text"]
            elif b_type == "paragraph":
                rich_text = block[b_type].get("rich_text", [])
                if rich_text: content = rich_text[0]["plain_text"][:30] + "..."
            
            print(f"   [{i+1}] Type: {b_type}, Content: {content}")
    else:
        print(f"❌ Blocks check failed: {res.status_code}")

if __name__ == "__main__":
    verify_notion_page(PAGE_ID)
