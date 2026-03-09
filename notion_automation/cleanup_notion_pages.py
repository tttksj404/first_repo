import requests
import os
import time

TOKEN = os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# List of redundant page IDs to archive (delete)
REDUNDANT_PAGES = [
    "318eacc8-175a-8099-b14d-f484fcbb1f18", # 나에게 부족한 것들
    "30beacc8-175a-8073-a52f-cca3d8cc8b63", # IM간축본
    "1677d48e-73f4-4e05-976d-0da8d115ccf0", # 🧠 삼성 A형 템플릿 요약 (암기용 Codex)
    "31eeacc8-175a-812b-b26a-e9d3a185d95e"  # [A형 합격] 재귀, 브루트포스... (Intermediate)
]

def archive_page(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}"
    try:
        response = requests.delete(url, headers=HEADERS)
        if response.status_code == 200:
            print(f"✅ Archived page: {page_id}")
        else:
            print(f"❌ Failed to archive {page_id}: {response.text}")
    except Exception as e:
        print(f"⚠️ Error archiving {page_id}: {str(e)}")

def main():
    print("🧹 Cleaning up redundant Notion pages...")
    for pid in REDUNDANT_PAGES:
        archive_page(pid)
        time.sleep(0.5)
    print("✨ Cleanup complete! Only the unified Masterbook remains.")

if __name__ == "__main__":
    main()
