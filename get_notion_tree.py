import requests
import json
import os
import sys
from pathlib import Path
from collections import defaultdict

sys.path.append(os.getcwd())
from notion_automation.core.notion_env import get_notion_token

TOKEN = get_notion_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_all_pages():
    pages = []
    has_more = True
    next_cursor = None
    url = "https://api.notion.com/v1/search"
    
    while has_more:
        payload = {
            "filter": {"property": "object", "value": "page"},
            "page_size": 100
        }
        if next_cursor:
            payload["start_cursor"] = next_cursor
            
        resp = requests.post(url, headers=HEADERS, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            pages.extend(data.get("results", []))
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
        else:
            print(f"Error fetching pages: {resp.status_code}")
            break
            
    return pages

def analyze_structure():
    pages = get_all_pages()
    
    # page_id -> info
    page_map = {}
    # parent_id -> list of child info
    children_map = defaultdict(list)
    root_pages = []
    
    for p in pages:
        page_id = p["id"]
        
        # Extract title
        title = "Untitled"
        props = p.get("properties", {})
        for k, v in props.items():
            if v.get("type") == "title":
                title_list = v.get("title", [])
                if title_list:
                    title = "".join(t.get("plain_text", "") for t in title_list)
                break
                
        # Extract parent
        parent = p.get("parent", {})
        parent_type = parent.get("type")
        parent_id = None
        
        if parent_type == "workspace":
            parent_id = "workspace"
        elif parent_type == "page_id":
            parent_id = parent.get("page_id")
        elif parent_type == "database_id":
            parent_id = parent.get("database_id")
            
        info = {
            "id": page_id,
            "title": title,
            "url": p.get("url"),
            "parent_type": parent_type,
            "parent_id": parent_id
        }
        
        page_map[page_id] = info
        
        if parent_type == "workspace":
            root_pages.append(info)
        elif parent_id:
            children_map[parent_id].append(info)
        else:
            root_pages.append(info) # fallback
            
    # Output structure
    print("=== NOTION WORKSPACE STRUCTURE ===")
    
    def print_tree(nodes, depth=0):
        for node in nodes:
            indent = "  " * depth
            print(f"{indent}- [{node['title']}] ({node['id']})")
            if node["id"] in children_map:
                print_tree(children_map[node["id"]], depth + 1)
                
    print_tree(root_pages)
    
    # Save to file for further analysis
    with open("notion_tree.json", "w", encoding="utf-8") as f:
        json.dump({
            "page_map": page_map,
            "children_map": children_map,
            "root_pages": root_pages
        }, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    analyze_structure()
