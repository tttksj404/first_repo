import json

with open("notion_pages_list.json", "r", encoding="utf-8") as f:
    pages = json.load(f)

problem_pages = []
for p in pages:
    if p["title"].startswith("📍"):
        problem_pages.append(p)

# Group by type if possible
# [Samsung A], [BFS], [DFS], etc.
grouped = {}
for p in problem_pages:
    title = p["title"]
    if "[" in title and "]" in title:
        tag = title[title.find("[")+1 : title.find("]")]
        if tag not in grouped: grouped[tag] = []
        grouped[tag].append(p)
    else:
        if "Other" not in grouped: grouped["Other"] = []
        grouped["Other"].append(p)

print("--- Detected Problem Pages ---")
for tag, p_list in grouped.items():
    print(f"\n[{tag}] ({len(p_list)} pages)")
    for p in p_list:
        print(f"  - {p['title']} ({p['id']})")

with open("problem_pages_grouped.json", "w", encoding="utf-8") as f:
    json.dump(grouped, f, ensure_ascii=False, indent=2)
