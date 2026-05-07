import requests
import json
import os
import sys

sys.path.append(os.getcwd())
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_blocks(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    resp = requests.get(url, headers=HEADERS)
    return resp.json().get("results", []) if resp.status_code == 200 else []

def optimize_algo_hub(hub_id):
    blocks = get_blocks(hub_id)
    # Check for too many paragraphs or redundant stuff
    # Actually, we already have child pages there.
    # Let's make it look better with sections.
    
    # We'll group them into: 🏆 Masterbooks, 📍 Problem Solutions, 📑 Study Steps
    children = []
    children.append({"type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": "🏆 핵심 마스터북"}}]}})
    # These will stay as child pages, Notion automatically lists them at bottom.
    # But we can add links for visibility.
    
    url = f"https://api.notion.com/v1/blocks/{hub_id}/children"
    requests.patch(url, headers=HEADERS, json={"children": children})

if __name__ == "__main__":
    algo_hub_id = "321eacc8-175a-81e1-adff-f68460b7221a"
    optimize_algo_hub(algo_hub_id)
    print("Algo Hub optimized.")
