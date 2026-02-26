import requests
import json

TOKEN = "REDACTED_NOTION_TOKEN"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def search_pages(query):
    url = "https://api.notion.com/v1/search"
    payload = {
        "query": query,
        "filter": {"value": "page", "property": "object"}
    }
    response = requests.post(url, json=payload, headers=HEADERS)
    return response.json()

if __name__ == "__main__":
    results = search_pages("알고리즘")
    for page in results.get("results", []):
        title = page.get("properties", {}).get("title", {}).get("title", [{}])[0].get("plain_text", "Untitled")
        print(f"Page Title: {title}, ID: {page['id']}")
