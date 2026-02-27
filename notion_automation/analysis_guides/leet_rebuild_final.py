import requests
import json
import time


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

def build():
    url = f"https://api.notion.com/v1/blocks/{PAGE_ID}/children"
    
    # Clean page
    res_get = requests.get(url, headers=HEADERS).json()
    for b in res_get.get('results', []):
        requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
        time.sleep(0.1)

    # Unicode-escaped content to avoid ANY SyntaxError
    content = [
        {"type": "table_of_contents", "table_of_contents": {}},
        {"type": "divider", "divider": {}},
        {"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": "\u110c\u1165\u11af\u1103\u1162 \u110b\u116f\u11ab\u110e\u1175\u11a8: \u1105\u1175\u1110\u1173\u1102\u1161\u11ab \u110c\u1175\u1102\u1173\u11bc\u110b\u1175 \u110b\u1161\u1102\u1175\u1105\u1161 \u1109\u1166\u1102\u116c\u1103\u1161. 40\u110b\u1175\u11af \u1100\u1175\u110e\u116e\u11af 4\u1112\u116c\u1103\u1169\u11a8 \u1109\u1175\u11af\u1109\u1171."}}], "icon": {"emoji": "🚨"}, "color": "red_background"}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "\u1100\u1175\u110e\u116e\u11af \u1109\u1166\u1102\u116c \u1106\u1161\u1109\u1173\u1110\u1165 \u1105\u1169\u1103\u1163\u1106\u1162\u11b8"}}]}},
        {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "3\u110b\u116d\u11af~4\u110b\u116d\u11af: 2016~2026 \u1100\u1175\u110e\u116e\u11af 4\u1112\u116c\u1103\u1169\u11a8. \u1109\u1173\u1101\u1162\u1102\u1165 \u110b\u1175\u11af\u1100\u1175 \u110e\u1166\u1112\u116c."}}]}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "✅ \u1103\u1166\u110b\u1175\u11af\u1105\u1175 \u110e\u1166\u1103\u1173\u1105\u1175\u1109\u1173\u1110\u1173"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "08:30 | \u110b\u1161\u110e\u1175\u1106 \u110b\u1168\u110b\u116d\u11af (7\u1107\u116e\u11ab \u110f\u1165\u11ba)"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "13:10 | \u110c\u1161\u11b7\u1109\u1175\u11b7 \u1110\u1173\u11b7\u1109\u1162 \u1111\u1106\u1173\u11af"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "20:15 | \u1100\u1175\u110e\u116e\u11af \u1109\u1166\u1102\u116c \u1111\u1107\u116e\u110b\u1175"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "22:30 | \u110b\u1169\u1103\u1161\u11a8 \u1102\u1169\u11ab\u1105\u1175 \u1105\u1175\u1111\u1169\u1110\u1173"}}]}},
        {"type": "to_do", "to_do": {"rich_text": [{"text": {"content": "23:00 | \u1109\u116e\u1106\u1167\u11ab \u1109\u1161\u1109\u116e (7\u1112\u116c\u1103\u1169\u11a8)"}}]}},
        {"type": "divider", "divider": {}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": "📝 \u1102\u1169\u11ab\u1105\u1175 \u1111\u1175\u1103\u1173\u1107\u1162\u11a8 \u110b\u1167\u11ab\u1100\u116e\u1109\u1169"}}]}},
        {"type": "callout", "callout": {"rich_text": [{"type": "text", "text": {"content": "\u110b\u1161\u1105\u1162\u110b\u1166 \u1106\u116e\u11ab\u110c\u1166 \u1107\u1165\u11ab\u1112\u1169\u110b\u1161 \u1102\u1161\u110b\u1174 \u1102\u1169\u11ab\u1105\u1175\u1105\u1173\u11af \u110c\u1165\u11a8\u110b\u1173\u1109\u1166\u110b\u116d. \u110c\u1166\u1100\u1161 \u110b\u1175\u11af\u1100\u1169 \u1111\u1175\u1103\u1173\u1107\u1162\u11a8\u110b\u1173\u11af \u1103\u1173\u1105\u1175\u11a8\u1100\u1166\u1109\u1173\u1107\u1102\u1175\u1103\u1161."}}], "icon": {"emoji": "🧪"}}}
    ]

    for i in range(0, len(content), 3):
        requests.patch(url, headers=HEADERS, json={"children": content[i:i+3]})
        time.sleep(0.5)
    print("SUCCESS")

if __name__ == "__main__":
    build()
