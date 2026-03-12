import json
from collections import defaultdict

def analyze_and_plan():
    with open("notion_tree.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        
    page_map = data["page_map"]
    
    # 1. Identify Duplicates
    title_to_ids = defaultdict(list)
    for pid, info in page_map.items():
        title_to_ids[info["title"]].append(pid)
        
    duplicates = {title: pids for title, pids in title_to_ids.items() if len(pids) > 1}
    
    # Categories planning
    categories = {
        "💻 알고리즘 & 코딩테스트": [],
        "🏛️ LEET & 로스쿨": [],
        "📚 개발 지식 & 기타": [],
        "🗑️ 보관함/삭제 대기": []
    }
    
    # Broad classification of existing top-level or significant pages
    for title, pids in title_to_ids.items():
        pid = pids[0] # take the first one
        if "삼성 A형" in title or "알고리즘" in title or "코테" in title or "Step" in title or "BFS" in title or "DFS" in title or "백트래킹" in title or "DP" in title:
            categories["💻 알고리즘 & 코딩테스트"].append(title)
        elif "LEET" in title or "추리" in title or "언어이해" in title or "로스쿨" in title:
            categories["🏛️ LEET & 로스쿨"].append(title)
        elif "ssafy" in title.lower() or "파이썬" in title or "AI" in title or "데이터 분석" in title:
            categories["📚 개발 지식 & 기타"].append(title)
            
    print("=== 🚨 중복 페이지 (병합/삭제 대상) ===")
    for title, pids in duplicates.items():
        print(f"- {title} ({len(pids)}개 존재)")
        
    print("\n=== 📂 제안하는 새로운 메인 대시보드 구조 ===")
    for cat, titles in categories.items():
        print(f"\n[ {cat} ]")
        for t in titles[:5]:
            print(f"  - {t}")
        if len(titles) > 5:
            print(f"  ... 외 {len(titles) - 5}개")
            
if __name__ == "__main__":
    analyze_and_plan()
