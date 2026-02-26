import requests
import json
import time

NOTION_TOKEN = "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"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def rebuild_page(pid, blocks):
    res_get = requests.get(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS)
    for b in res_get.json().get("results", []): requests.delete(f"https://api.notion.com/v1/blocks/{b['id']}", headers=HEADERS)
    requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": blocks})

# 3. [Samsung A] 스타트와 링크 - IM 초격차 상세 버전
link_blocks = [
    {"type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📍 [Problem 03] 스타트와 링크 - 백트래킹 기반 조합 최적화"}}]}},
    {"type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": "문제 요약: $N$명을 두 팀으로 나누어 시너지 합의 차이를 최소화하는 문제입니다. $N$이 최대 20으로 작아 백트래킹(DFS)을 이용한 모든 조합 탐색이 가능합니다."}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "1. 논리적 상태 관리 (State Management)"}}]}},
    {"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "이 문제의 핵심은 '누가 어떤 팀에 속하는가'를 중복 없이 효율적으로 나누는 것입니다."}}]}},
    {"type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": "① 백트래킹을 이용한 조합 생성"}}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "핵심 로직"}, "annotations": {"bold": True}}, {"type": "text", "text": ": dfs(idx, count) 함수에서 한 명씩 선택해가며 count가 N/2가 되는 순간을 포착합니다. 이때 visited 배열의 True/False가 두 팀을 가르는 기준이 됩니다."}]}},
    {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "시너지 계산"}, "annotations": {"bold": True}}, {"type": "text", "text": ": 팀이 결정되면 2중 for문으로 모든 (i, j) 쌍에 대해 S[i][j] + S[j][i]를 합산합니다."}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💻 Python 초정밀 실전 코드"}}]}},
    {"type": "code", "code": {"language": "python", "rich_text": [{"type": "text", "text": {"content": '''def dfs(idx, cnt):
    global min_diff
    if cnt == N // 2:
        start, link = 0, 0
        for i in range(N):
            for j in range(N):
                if visited[i] and visited[j]:
                    start += S[i][j]
                elif not visited[i] and not visited[j]:
                    link += S[i][j]
        min_diff = min(min_diff, abs(start - link))
        return

    for i in range(idx, N):
        if not visited[i]:
            visited[i] = True
            dfs(i + 1, cnt + 1)
            visited[i] = False'''}}]}},
    {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "5. 시험장 필살 체크리스트"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "0번 멤버를 한 팀에 고정하여 전체 연산량을 절반으로 줄였는가? (대칭성 활용)"}}]}},
    {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": "능력치 합산 시 S[i][j]와 S[j][i]를 모두 고려했는가?"}}]}},
    {"type": "callout", "callout": {
        "icon": {"type": "emoji", "emoji": "💡"},
        "color": "blue_background",
        "rich_text": [{"type": "text", "text": {"content": "학생 가이드: 조합 라이브러리를 써도 되지만, 백트래킹을 직접 짜는 연습을 하세요. 조건이 복잡해질수록(예: 세 팀으로 나누기) 직접 구현 능력이 중요해집니다."}}]
    }}
]

rebuild_page("313eacc8-175a-8102-92f6-de849db9395d", link_blocks)
print("Link page rebuilt.")
