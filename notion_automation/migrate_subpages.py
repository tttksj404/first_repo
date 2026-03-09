import requests
import os
import time

TOKEN = os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}
MASTER_PAGE_ID = "31eeacc8-175a-8183-b982-f39616d86dce"

# 1. Algorithm Library Pages (Theory)
LIBRARY_PAGES = [
    "2f0eacc8-175a-8072-8e4b-e298edcb69c5", # 재귀&백트래킹
    "2f0eacc8-175a-805c-85b2-dca59899d3d8", # DFS/BFS
    "30ceacc8-175a-804d-9888-cf3288329719", # 다익스트라
    "302eacc8-175a-8072-aad8-db2ca96b67e4", # DP 탐색
    "2feeacc8-175a-80ee-9739-cb395ef4cc64", # 투포인터,그리디
    "2faeacc8-175a-8009-9587-edcfe01dbb4e", # 이진 탐색
    "2e7eacc8-175a-8049-8859-c2d0efe9cbe4", # 해시
    "2f3eacc8-175a-8022-970c-c9c4ed4f1c43", # 시뮬레이션
    "2e7eacc8-175a-803b-af45-d17145aba517", # 배열 & 문자열 
    "2eaeacc8-175a-80fa-98b4-e0a61bda22cb"  # 스택&큐
]

# 2. Practical Technique Mastery
TECHNIQUE_PAGES = [
    "2fceacc8-175a-8097-8a09-dec951049ee0", # 격자탐색 마스터
    "2fceacc8-175a-8049-a889-f4dfad72a7de", # 2차원 배열의 응용
    "2ffeacc8-175a-80dd-b167-d583f11597a3", # 회문분석
    "2fdeacc8-175a-8054-81f4-ecb052b4d0fe", # 차분배열, 누적합
    "2fceacc8-175a-80bf-bfc1-eb2daffafad5", # 인덱스 사용법
    "2fbeacc8-175a-8057-8677-e1da08202692", # 입력 출력 방법들
    "310eacc8-175a-806b-a9cb-ddfec721be71"  # 반복문 혹은 원형에서의 반복
]

# 3. Step Series (To Archive after verification - or just move for safety)
STEP_SERIES = [
    "318eacc8-175a-81a3-bd79-f510656ff6d5", # Step1
    "318eacc8-175a-8177-af49-ebcc4f2487b0", # Step2
    "318eacc8-175a-81d8-a077-dd9def363cf6", # Step3
    "318eacc8-175a-8129-a114-c74c4d8f911a", # Step4
    "318eacc8-175a-81b3-ac03-e73d137c307b"  # Step5
]

def move_page(page_id, new_parent_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "parent": {"page_id": new_parent_id}
    }
    res = requests.patch(url, headers=HEADERS, json=payload)
    if res.status_code == 200:
        print(f"✅ Moved page {page_id}")
    else:
        print(f"❌ Failed to move {page_id}: {res.text}")

def main():
    print("🚀 Starting 2nd Final Consolidation...")
    
    # 1. Create grouping headers in Masterbook first (Optional, move_page will list them as subpages)
    # Moving theory pages
    print("\n--- Moving Theory Library ---")
    for pid in LIBRARY_PAGES:
        move_page(pid, MASTER_PAGE_ID)
        time.sleep(0.3)
        
    # Moving technique pages
    print("\n--- Moving Technique Mastery ---")
    for pid in TECHNIQUE_PAGES:
        move_page(pid, MASTER_PAGE_ID)
        time.sleep(0.3)
        
    # Moving step series
    print("\n--- Moving Step Series ---")
    for pid in STEP_SERIES:
        move_page(pid, MASTER_PAGE_ID)
        time.sleep(0.3)

    print("\n✨ All pages migrated under the Masterbook!")

if __name__ == "__main__":
    main()
