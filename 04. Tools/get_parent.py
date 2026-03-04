import requests
import os
from pathlib import Path

def get_token():
    paths = [Path(".env.notion"), Path("notion_automation/.env.notion")]
    for p in paths:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if "NOTION_TOKEN" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv("NOTION_TOKEN")

token = get_token()
headers = {
    "Authorization": f"Bearer {token}",
    "Notion-Version": "2022-06-28"
}

# 313eacc8-175a-81d1-8add-c2ee0f78236d (연구소)
r = requests.get("https://api.notion.com/v1/pages/313eacc8175a81d18addc2ee0f78236d", headers=headers)
print(r.json().get("parent"))
