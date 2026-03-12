import requests
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

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
    if resp.status_code == 200:
        return resp.json().get("results", [])
    return []

def analyze_duplicates(duplicates_dict):
    """
    duplicates_dict: {title: [id1, id2, ...]}
    """
    report = {}
    
    def fetch_and_summarize(title, pid):
        blocks = get_blocks(pid)
        # Simple heuristic: count of blocks and characters
        text_content = ""
        for b in blocks:
            b_type = b.get("type")
            if b_type in ["paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item"]:
                rt = b.get(b_type, {}).get("rich_text", [])
                text_content += "".join([t.get("plain_text", "") for t in rt])
        
        return {
            "id": pid,
            "title": title,
            "block_count": len(blocks),
            "char_count": len(text_content),
            "snippet": text_content[:100]
        }

    for title, pids in duplicates_dict.items():
        print(f"Analyzing '{title}'...")
        with ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(lambda pid: fetch_and_summarize(title, pid), pids))
        report[title] = results
        
    return report

if __name__ == "__main__":
    # From previous plan_notion_structure.py output
    dups = {
        "🏆 [Master] 삼성 A형 알고리즘 백지코딩 마스터북": [
            "31eeacc8-175a-8122-bc26-ca316b8f2c44",
            "31eeacc8-175a-81f0-97a1-e84a739c4b26",
            "31eeacc8-175a-8183-b982-f39616d86dce"
        ],
        "📍 [Samsung A] 풍선 팡 (재귀 & 브루트포스)": [
            "31beacc8-175a-81e9-a302-dec0633ff5ea",
            "319eacc8-175a-81ac-aecf-dbc7aacebc69"
        ],
        "📍 [Samsung A] 장기 포의 이동 (DFS & 백트래킹)": [
            "31beacc8-175a-81db-acda-fa02ac631576",
            "319eacc8-175a-81e0-9669-f9661759d4f0"
        ],
        "📍 [Samsung A] 몬스터 소탕 (DFS & 순열)": [
            "31beacc8-175a-81de-96b2-dc42b14ff10a",
            "319eacc8-175a-81c5-8bd2-ea179bf83820"
        ],
        "📍 [BFS] 2178 - 미로 탐색 (최단 경로)": [
            "31beacc8-175a-8150-8859-e5dd986c528c",
            "319eacc8-175a-8168-98f3-e63ceafa8736"
        ]
    }
    
    report = analyze_duplicates(dups)
    with open("duplicate_analysis.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print("\nAnalysis complete. Results saved to duplicate_analysis.json")
