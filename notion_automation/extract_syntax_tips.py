import os
import re
import json

def extract_syntax_tips(directory):
    tips = []
    # Keywords to look for in comments or code
    patterns = {
        "Input/Output": [r"input", r"sys.stdin.readline", r"print", r"f-string", r"strip"],
        "List/Array": [r"list", r"append", r"pop", r"sort", r"sorted", r"zip", r"comprehension"],
        "Matrix/Grid": [r"zip\(\*", r"delta", r"dr", r"dc", r"nr", r"nc"],
        "Data Structures": [r"deque", r"set", r"dict", r"heapq", r"Counter"],
        "Recursion/Backtracking": [r"dfs", r"recursionlimit", r"visited", r"backtracking"],
        "Built-ins/Math": [r"map", r"math", r"floor", r"ceil", r"abs", r"min", r"max", r"enumerate"]
    }
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        content = "".join(lines)
                        
                        # Extract comments
                        comments = [l.strip() for l in lines if l.strip().startswith("#")]
                        
                        # Find matching patterns
                        found_categories = []
                        for cat, regs in patterns.items():
                            if any(re.search(reg, content, re.IGNORECASE) for reg in regs):
                                found_categories.append(cat)
                        
                        if found_categories or comments:
                            tips.append({
                                "file": file,
                                "path": path,
                                "categories": found_categories,
                                "comments": comments[:10] # Top 10 comments
                            })
                except Exception as e:
                    pass
    return tips

tips = extract_syntax_tips("gitp")
with open("extracted_python_tips.json", "w", encoding="utf-8") as f:
    json.dump(tips, f, ensure_ascii=False, indent=2)

print(f"✅ Extracted tips from {len(tips)} files.")
