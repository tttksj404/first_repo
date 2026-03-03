# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from notion_automation.core.notion_env import get_notion_token
import requests
import json
import sys

# Ensure UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')
TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def append_blocks(page_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    payload = {"children": blocks}
    res = requests.patch(url, json=payload, headers=HEADERS)
    if res.status_code != 200:
        print(f"Error appending blocks: {res.text}")

# ?숈깮 ?쒖젏??蹂닿컯??而⑦뀗痢?(?쒓? ?ы븿)
# ??釉붾줉?ㅼ? '湲곗〈 ?댁슜' ?ㅼ뿉 遺숆쾶 ?⑸땲??
STUDENT_NOTES = [
    {"object": "block", "type": "divider", "divider": {}},
    {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "?럳 ?숈깮???쒖꽑: DFS/BFS瑜?怨듬??섎ŉ ?먮? ?듭떖 ?뺣━"}}]}},
    {"object": "block", "type": "callout", "callout": {
        "rich_text": [{"text": {"content": "泥섏쓬?먮뒗 DFS? BFS媛 鍮꾩듂??蹂댁??붾뜲, '理쒕떒 嫄곕━'瑜?臾쇱뼱蹂대㈃ BFS瑜? '紐⑤뱺 寃쎈줈 ?먯깋'?대굹 '源딆씠'媛 以묒슂?섎떎硫?DFS瑜??곕뒗 寃?援?０?대씪??嫄?源⑤떖?섏뒿?덈떎!"}}],
        "icon": {"emoji": "?뮕"}
    }},
    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "?좑툘 ?닿? ?ㅼ닔?덈뜕 遺遺?(Mistake Notes)"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "DFS ?ш? ?몄텧 ??諛⑸Ц 泥섎━瑜?'?ㅼ뼱媛湲??????좎?, '?ㅼ뼱???????좎? ?룰컝?몃뒗?? ?쇨????덇쾶 '???ㅽ깮???ｊ린 吏곸쟾'???섎뒗 寃?以묐났 諛⑸Ц??留됰뒗 ??媛???덉쟾?섎뜑?쇨퀬??"}}]}},
    {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"text": {"content": "BFS?먯꽌 collections.deque瑜????곌퀬 ?쇰컲 list.pop(0)???쇰떎媛 ?쒓컙 珥덇낵(O(N))濡?怨좎깮???곸씠 ?덉뒿?덈떎. 臾댁“嫄?popleft()瑜??곸떆??"}}]}},
    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "?? ?ㅼ쟾 ?묒슜: 硫?곗냼??BFS (7576 ?좊쭏????"}}]}},
    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "?쒖옉?먯씠 ?щ윭 媛쒖씤 寃쎌슦, 媛곴컖 BFS瑜??뚮━??寃??꾨땲??'紐⑤뱺 ?쒖옉?먯쓣 ?쒓볼踰덉뿉 ?먯뿉 ?ｊ퀬' ?쒖옉?섎뒗 寃??ъ씤?몄엯?덈떎. 洹몃옒??媛?吏?먭퉴吏??理쒕떒 嫄곕━媛 ?숈떆???쇱졇?섍?硫??뺣떟???섏샃?덈떎."}}]}},
    {"object": "block", "type": "code", "code": {
        "language": "python",
        "rich_text": [{"text": {"content": "# Multi-source BFS logic: Enqueue all start nodes first\nqueue = deque()\nfor r in range(N):\n    for c in range(M):\n        if grid[r][c] == 1: # Starting points\n            queue.append((r, c))\n            visited[r][c] = 0"}}]
    }},
    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "?뱦 肄붾뱶 ?묒꽦 ?쒗뵆由?(湲곗뼲??"}}]}},
    {"object": "block", "type": "quote", "quote": {"rich_text": [{"text": {"content": "1. 臾몄젣 ?쎄퀬 DFS vs BFS 寃곗젙\n2. ?곹븯醫뚯슦(dr, dc) ?ㅼ젙\n3. 諛⑸Ц 泥섎━ 諛곗뿴(visited) ?앹꽦\n4. 踰붿쐞 泥댄겕(is_valid) + 諛⑸Ц ?щ? ?뺤씤\n5. 寃곌낵媛??꾩텧 (理쒕?媛? 理쒖냼媛? 媛쒖닔 ??"}}]}}
]

if __name__ == "__main__":
    page_id = "2f0eacc8-175a-805c-85b2-dca59899d3d8"
    print("Appending rich algorithm notes to page...")
    append_blocks(page_id, STUDENT_NOTES)
    print("Update complete!")



