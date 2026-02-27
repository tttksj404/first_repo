import requests
import json
import time

# 1. API Configuration

import os

def _get_notion_token():
    # Try multiple paths to find notion_key.txt
    current_dir = os.path.dirname(os.path.abspath(__file__))
    paths = [
        os.path.join(current_dir, 'notion_key.txt'),
        os.path.join(current_dir, '..', 'core', 'notion_key.txt'),
        os.path.join(current_dir, 'core', 'notion_key.txt'),
        os.path.join(os.getcwd(), 'notion_automation', 'core', 'notion_key.txt')
    ]
    for p in paths:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                token = f.read().strip()
                if token: return token
    return os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")

NOTION_TOKEN = _get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
PAGE_ID = "314eacc8-175a-817c-8fa6-c89fd1e36a66"

def rebuild():
    print("--- 🛠️ FINAL REBUILDING: ULTRA-DENSITY ---")
    
    # Clean old content
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{PAGE_ID}/children", headers=HEADERS)
    for b in res_get.json().get('results', []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.1)

    # 1. High-Density Strategy Content
    content = [
        {"type": "table_of_contents", "table_of_contents": {}},
        {"type": "divider", "divider": {}},
        {"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": "🏆 Target: LEET 140+
🚫 Rules: No Leak, No Re-reading, 40-Day Brainwashing"}}], "icon": {"emoji": "🎓"}, "color": "blue_background"}},
        
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🔍 Ⅰ. Scanner Reading & Triangle Strategy"}}]}},
        {"type": "quote", "quote": {"rich_text": [{"text": {"content": "LEET is a speed game. Don't understand 100%. Just mark the locations of info. 고민은 선지 헷갈릴 때만 한다."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "Scanner: 토씨 하나 안 빼놓고 기계적으로 스캔. 멈추기 금지."}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "Triangle: 10초 이상 고민 시 즉시 세모 치고 다음 선지 전진."}}]}},
        
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "📅 Ⅱ. 40-Day / 4-Iteration Curriculum"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "Iter 1: Mastering Scanner Reading.
Iter 2-4: Brainwashing with official logic."}}]}},
        
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "⏰ Ⅲ. Daily Routine Checklist (Check here!)"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🌅 08:30 | Scanner Warm-up (1 Passage, 7min limit)"}}], "checked": False}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🏢 09:00 | SSAFY Algorithm x LEET Connection"}}], "checked": False}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🍴 13:10 | Lunch Short Puzzle (3 Logic Games)"}}], "checked": False}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "🔥 20:15 | Actual Brainwashing (1 Full Year Set)"}}], "checked": False}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "📝 22:30 | Wrong Logic Report (30min Limit)"}}], "checked": False}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "💤 23:00 | Mandatory Deep Sleep (7 Hours)"}}], "checked": False}},
        
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "🤖 Ⅳ. AI Feedback Loop System"}}]}},
        {"type": "callout", "callout": {"rich_text": [{"text": {"content": "Write your 'Wrong Logic' below. Ask me 'Analyze my logic' -> I will read this page and append expert feedback."}}], "icon": {"emoji": "📡"}, "color": "purple_background"}},
        
        {"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "📝 Logic Feedback Lab (Write Here)"}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "[Problem No / My Logic / Correct Reason / Next Action]"}, "annotations": {"italic": True}}]}},
        {"type": "divider", "divider": {}}
    ]

    # Patch Blocks
    url_patch = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    for i in range(0, len(content), 3):
        res = requests.patch(url_patch, headers=HEADERS, json={"children": content[i:i+3]})
        if res.status_code == 200: print(f"Chunk {i//3 + 1} deployed.")
        else: print(f"Error: {res.text}")
        time.sleep(1)

if __name__ == "__main__":
    rebuild()
