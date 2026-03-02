import requests
import os
import json
from dotenv import load_dotenv

def get_token():
    load_dotenv()
    token = os.getenv("NOTION_TOKEN")
    if token: return token
    try:
        with open('.gemini/settings.json', 'r') as f:
            settings = json.load(f)
            token = settings.get("NOTION_TOKEN")
            if token: return token
    except: pass
    return None

TOKEN = get_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": "2022-06-28"
}

def get_block_content(block_id):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    blocks = []
    has_more = True
    next_cursor = None
    while has_more:
        params = {"start_cursor": next_cursor} if next_cursor else {}
        res = requests.get(url, headers=HEADERS, params=params)
        if res.status_code != 200: break
        data = res.json()
        blocks.extend(data.get("results", []))
        has_more = data.get("has_more")
        next_cursor = data.get("next_cursor")
    return blocks

def block_to_markdown(block):
    b_type = block.get("type")
    content = ""
    def get_text(rich_texts):
        return "".join([t.get("plain_text", "") for t in rich_texts])

    if b_type == "paragraph":
        content = get_text(block["paragraph"]["rich_text"]) + "\n"
    elif b_type.startswith("heading_"):
        level = b_type.split("_")[1]
        content = ("#" * int(level)) + " " + get_text(block[b_type]["rich_text"]) + "\n"
    elif b_type == "bulleted_list_item":
        content = "- " + get_text(block["bulleted_list_item"]["rich_text"]) + "\n"
    elif b_type == "numbered_list_item":
        content = "1. " + get_text(block["numbered_list_item"]["rich_text"]) + "\n"
    elif b_type == "to_do":
        mark = "[x]" if block["to_do"]["checked"] else "[ ]"
        content = f"{mark} " + get_text(block["to_do"]["rich_text"]) + "\n"
    elif b_type == "code":
        lang = block["code"]["language"]
        code = get_text(block["code"]["rich_text"])
        content = f"```{lang}\n{code}\n```\n"
    elif b_type == "quote":
        content = "> " + get_text(block["quote"]["rich_text"]) + "\n"
    elif b_type == "callout":
        emoji = block["callout"].get("icon", {}).get("emoji", "💡")
        content = f"> {emoji} " + get_text(block["callout"]["rich_text"]) + "\n"
    
    if block.get("has_children"):
        children = get_block_content(block["id"])
        child_md = ""
        for child in children:
            child_md += block_to_markdown(child)
        content += "\n".join(["    " + line for line in child_md.split("\n") if line]) + "\n"
    return content

def export_page(page_id, filename):
    print(f"📄 '{filename}' 추출 중...")
    blocks = get_block_content(page_id)
    md_output = ""
    for block in blocks:
        md_output += block_to_markdown(block)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(md_output)
    print(f"✅ {filename} 저장 완료.")

if __name__ == "__main__":
    export_page("314eacc8-175a-819d-985b-ee4f4d006c90", "Notion_Reasoning_Mastery.md")
    export_page("314eacc8-175a-81b4-8cf7-cb7076a084c0", "Notion_Verbal_Understanding.md")
