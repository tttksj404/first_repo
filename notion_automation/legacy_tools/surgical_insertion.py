# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from notion_automation.core.notion_env import get_notion_token
import requests
import json
TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def insert_blocks(page_id, blocks, after_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    payload = {
        "children": blocks,
        "after": after_id
    }
    requests.patch(url, json=payload, headers=HEADERS)

if __name__ == "__main__":
    page_id = "2f0eacc8-175a-805c-85b2-dca59899d3d8"
    
    # 1. ?쒕ぉ(Index 0) 諛붾줈 ?ㅼ뿉 紐⑹감? ?명듃濡??쎌엯
    # after_id: 2f0eacc8-175a-8083-b095-c14951296b30 (Heading 1 ID)
    intro_blocks = [
        {"object": "block", "type": "table_of_contents", "table_of_contents": {}},
        {"object": "block", "type": "callout", "callout": {
            "rich_text": [{"text": {"content": "?뮕 ???섏씠吏???ъ슜?먮떂???뺣━?섏떊 ?뺤꽍 肄붾뱶?ㅼ쓣 湲곕컲?쇰줈, ?쒓? 怨듬??섎ŉ 源⑤떖? ?곷뱾??以묎컙以묎컙 ?㏓텤??留뚮뱺 醫낇빀 ?숈뒿?μ엯?덈떎. 湲곗〈 ?댁슜? 洹몃?濡?蹂댁〈?섏뼱 ?덉쑝???덉떖?섍퀬 ?숈뒿?섏꽭??"}}],
            "icon": {"emoji": "?럳"}
        }},
        {"object": "block", "type": "divider", "divider": {}}
    ]
    print("Inserting Table of Contents and Intro...")
    insert_blocks(page_id, intro_blocks, "2f0eacc8-175a-8083-b095-c14951296b30")

    # 2. DFS ?뱀뀡(Index 10) ?욎뿉 釉뚮┸吏 ?쎌엯
    # after_id: 2f0eacc8-175a-806c-9250-fbfecc99d3cd (Divider before DFS)
    dfs_bridge = [
        {"object": "block", "type": "callout", "callout": {
            "rich_text": [{"text": {"content": "?뵇 ?ш린?쒕??곕뒗 DFS???곸뿭?낅땲?? ?ㅽ깮?대굹 ?ш?瑜??ъ슜?섏뿬 源딄쾶 ?ㅼ뼱媛???먯깋???뺤닔瑜??먭뺨蹂댁꽭??"}}],
            "icon": {"emoji": "?륅툘"}
        }}
    ]
    print("Inserting DFS Bridge...")
    insert_blocks(page_id, dfs_bridge, "2f0eacc8-175a-806c-9250-fbfecc99d3cd")

    # 3. BFS ?뱀뀡(Index 81) ?욎뿉 釉뚮┸吏 ?쎌엯
    # after_id: 2f0eacc8-175a-80e2-b982-c4bb476856ff (Divider before BFS)
    bfs_bridge = [
        {"object": "block", "type": "callout", "callout": {
            "rich_text": [{"text": {"content": "?뙄 ?댁젣 BFS濡??섏뼱媛묐땲?? ??Queue)瑜??ъ슜?섏뿬 臾쇨껐泥섎읆 ?쇱졇?섍???理쒕떒 嫄곕━ ?먯깋???쒖옉?⑸땲??"}}],
            "icon": {"emoji": "?뙄"}
        }}
    ]
    print("Inserting BFS Bridge...")
    insert_blocks(page_id, bfs_bridge, "2f0eacc8-175a-80e2-b982-c4bb476856ff")

    print("Surgical Insertion Complete!")



