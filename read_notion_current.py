# -*- coding: utf-8 -*-
import requests
import json

TOKEN = "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"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_page_blocks(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    response = requests.get(url, headers=HEADERS)
    return response.json().get("results", [])

if __name__ == "__main__":
    # DFS/BFS 페이지 ID
    dfs_bfs_id = "2f0eacc8-175a-805c-85b2-dca59899d3d8"
    blocks = get_page_blocks(dfs_bfs_id)
    
    print(f"--- Current Content of DFS/BFS Page ---")
    for block in blocks:
        b_type = block['type']
        content = block.get(b_type, {})
        text_list = content.get('rich_text', [])
        if text_list:
            print(f"[{b_type}] {text_list[0].get('plain_text', '')}")
        else:
            print(f"[{b_type}] (No Text)")
