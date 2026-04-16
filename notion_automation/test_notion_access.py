from __future__ import annotations

import os

import pytest
import requests


TOKEN = os.getenv("NOTION_TOKEN", "").strip()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


@pytest.mark.skip(reason="manual Notion connectivity smoke test")
def test_id(page_id: str) -> None:
    url = f"https://api.notion.com/v1/pages/{page_id}"
    res = requests.get(url, headers=HEADERS, timeout=15)
    assert res.status_code in {200, 404, 401}
