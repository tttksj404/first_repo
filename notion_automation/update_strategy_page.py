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

def delete_block(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}"
    res = requests.delete(url, headers=HEADERS)
    return res.status_code == 200

def append_blocks(block_id, children, after=None):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    payload = {"children": children}
    if after:
        payload["after"] = after
    res = requests.patch(url, headers=HEADERS, json=payload)
    return res.status_code == 200

def main():
    # DFS & 백트래킹 극한정복
    strategy_page_id = "31beacc8-175a-813c-ba9b-c0ff8e8d5d98"
    
    # 1. Delete redundant blocks
    to_delete = [
        "31beacc8-175a-81d3-95a8-e25b4fadbb30", # Heading 3
        "31beacc8-175a-81f9-a35c-c055578ada2b"  # Code block
    ]
    
    for bid in to_delete:
        if delete_block(bid):
            print(f"Deleted block {bid}")
        else:
            print(f"Failed to delete block {bid}")
            
    # 2. Insert link to Masterbook
    # We'll insert it after the "구현 체크리스트" section (ID: 31beacc8-175a-81b6-90a6-c3f861baf948 is the heading)
    # But wait, there are bullet points after it.
    # Let's just append it to the top or after the last bullet point of section 2.
    # The last bullet point of section 2 is 31beacc8-175a-817a-8a69-ffaaca95e2b8.
    
    masterbook_id = "31feacc8175a815cab4bcc5da3b4d039"
    link_block = {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {
                        "content": "📍 순열/조합/부분집합 표준 템플릿은 ",
                        "link": None
                    }
                },
                {
                    "type": "text",
                    "text": {
                        "content": "📕 [마스터북] 백트래킹 3대 천왕",
                        "link": {"url": f"https://www.notion.so/{masterbook_id}"}
                    }
                },
                {
                    "type": "text",
                    "text": {
                        "content": " 페이지에서 통합 관리됩니다. (Single Source of Truth)",
                        "link": None
                    }
                }
            ],
            "icon": {"emoji": "📚"}
        }
    }
    
    if append_blocks(strategy_page_id, [link_block], after="31beacc8-175a-817a-8a69-ffaaca95e2b8"):
        print("Successfully added link to Masterbook in Strategy page")
    else:
        print("Failed to add link to Masterbook")

if __name__ == "__main__":
    main()
