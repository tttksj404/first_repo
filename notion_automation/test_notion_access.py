import requests
import os
import json

TOKEN = os.getenv("NOTION_TOKEN", "YOUR_NOTION_TOKEN_HERE")
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def test_id(page_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    res = requests.get(url, headers=HEADERS)
    print(f"Testing Page {page_id}: {res.status_code}")
    if res.status_code == 200:
        print(f"  Title: {res.json().get('properties', {}).get('title', {}).get('title', [{}])[0].get('plain_text')}")
    else:
        print(f"  Error: {res.text}")

# Testing the page ID from the list
test_id("2ebeacc8-175a-803e-98e8-d832509624c1")
test_id("2ebeacc8175a803e98e8d832509624c1")

# Also test another one that worked before (Weak Points)
test_id("318eacc8-175a-8099-b14d-f484fcbb1f18")
