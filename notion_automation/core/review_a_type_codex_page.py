import argparse
import os
import time
from pathlib import Path
from typing import Any

import requests

NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"
TARGET_TITLE = "🧠 삼성 A형 템플릿 요약 (암기용 Codex)"


def load_env_files() -> None:
    candidates = [
        Path(".env"),
        Path(".env.notion"),
        Path("notion_automation/.env.notion"),
    ]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip()
            value = v.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


def get_notion_token() -> str:
    load_env_files()
    token = (
        os.getenv("NOTION_TOKEN", "").strip()
        or os.getenv("notion_api_key", "").strip()
        or os.getenv("NOTION_API_KEY", "").strip()
    )
    if token:
        return token
    raise RuntimeError(
        "Notion token is missing. Set NOTION_TOKEN or notion_api_key in .env/.env.notion."
    )


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_notion_token()}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def api_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    last_err: str | None = None
    for attempt in range(1, 5):
        try:
            resp = requests.request(
                method=method, url=url, headers=headers(), json=payload, timeout=25
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = f"{resp.status_code}: {resp.text[:200]}"
                time.sleep(min(2**attempt, 8))
                continue
            resp.raise_for_status()
            return resp.json() if resp.text else {}
        except requests.RequestException as exc:
            last_err = str(exc)
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"Notion API failed ({method} {path}): {last_err}")


def extract_title(page: dict[str, Any]) -> str:
    props = page.get("properties", {})
    for _, p in props.items():
        if p.get("type") == "title":
            t = "".join(x.get("plain_text", "") for x in p.get("title", []))
            return t.strip()
    return ""


def find_page_by_title(title: str) -> dict[str, Any]:
    data = api_request(
        "POST",
        "/search",
        {
            "query": title,
            "filter": {"value": "page", "property": "object"},
            "page_size": 50,
        },
    )
    matches = []
    for r in data.get("results", []):
        t = extract_title(r)
        if t == title:
            matches.append(r)
    if matches:
        return matches[0]
    # fallback: first partial match
    for r in data.get("results", []):
        t = extract_title(r)
        if title in t or t in title:
            return r
    raise RuntimeError(f"Target page not found: {title}")


def fetch_all_children(block_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        path = f"/blocks/{block_id}/children?page_size=100"
        if cursor:
            path += f"&start_cursor={cursor}"
        data = api_request("GET", path)
        results = data.get("results", [])
        out.extend(results)
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return out


def rich_text_content(block: dict[str, Any]) -> str:
    btype = block.get("type", "")
    inner = block.get(btype, {})
    rich = inner.get("rich_text", [])
    return "".join(rt.get("plain_text", "") for rt in rich).strip()


def flatten_text(blocks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for b in blocks:
        text = rich_text_content(b)
        if text:
            lines.append(text)
    return "\n".join(lines)


RUBRIC: list[tuple[str, list[str], int]] = [
    ("격자/델타 기본형", ["dr", "dc", "범위", "델타", "격자"], 15),
    ("구현 템플릿", ["회전", "중력", "동시", "시뮬레이션", "스냅샷"], 15),
    ("탐색 템플릿", ["bfs", "dfs", "visited", "큐", "백트래킹"], 15),
    ("최적화 템플릿", ["다익스트라", "이분탐색", "파라메트릭", "위상정렬", "dp"], 15),
    ("실수 방지 체크", ["인덱스", "초기화", "경계", "복구", "예외"], 10),
    ("시간복잡도 판단", ["시간복잡도", "O(", "최악", "가지치기"], 10),
    ("시험 운영 전략", ["입력", "디버깅", "반례", "시간 배분", "순서"], 10),
    ("암기용 요약", ["템플릿", "체크리스트", "암기", "1분", "요약"], 10),
]


def score_page(text: str) -> tuple[int, list[str], list[str]]:
    lower = text.lower()
    score = 0
    met: list[str] = []
    missing: list[str] = []
    for name, keywords, weight in RUBRIC:
        if any(kw.lower() in lower for kw in keywords):
            score += weight
            met.append(name)
        else:
            missing.append(name)
    return score, met, missing


def h2(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": text[:1800]}}]},
    }


def bullet(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text[:1800]}}]},
    }


def code(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "code",
        "code": {
            "language": "python",
            "rich_text": [{"type": "text", "text": {"content": text[:1800]}}],
        },
    }


def callout(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": "🧠"},
            "rich_text": [{"type": "text", "text": {"content": text[:1800]}}],
        },
    }


def build_boost_blocks() -> list[dict[str, Any]]:
    snippet = """# 4방향 델타 + 경계 체크 템플릿
dr = [-1, 1, 0, 0]
dc = [0, 0, -1, 1]
for d in range(4):
    nr, nc = r + dr[d], c + dc[d]
    if 0 <= nr < N and 0 <= nc < M:
        pass
"""
    snippet2 = """# 시뮬레이션 동시 반영(스냅샷) 템플릿
changes = []
for r in range(N):
    for c in range(M):
        # 현재 상태 기준으로 계산
        if need_change:
            changes.append((r, c, new_val))
for r, c, v in changes:
    board[r][c] = v
"""
    return [
        h2("🚨 A형 전날 보강: 합격용 최소 템플릿 팩"),
        callout("이 섹션은 시험 전 암기를 위한 초압축 보강본입니다. 문제를 못 풀어도 형식 구현을 시작할 수 있게 설계했습니다."),
        h2("1) 구현 시작 60초 루틴"),
        bullet("입력 크기(N, M, K)와 종료 조건(정확히 T번 / 안정화까지)을 먼저 한 줄로 적는다."),
        bullet("보드/방문/큐/우선순위큐/딕셔너리 중 필요한 자료구조를 즉시 선언한다."),
        bullet("상태 전이는 함수 하나로 분리한다: move(), spread(), rotate(), bfs(), dfs()."),
        bullet("동시 반영이 필요한 문제는 즉시 스냅샷(changes 리스트) 방식으로 고정한다."),
        h2("2) A형 구현 필수 템플릿"),
        code(snippet),
        code(snippet2),
        bullet("회전/중력/충돌 문제는 '읽기 단계'와 '쓰기 단계'를 분리한다."),
        bullet("한 턴이 끝날 때마다 불변식 검증: 개수 합, 좌표 범위, 방문배열 초기화 상태."),
        h2("3) 실수 방지 체크리스트 (암기)"),
        bullet("인덱스: 0-based/1-based 혼용 여부를 입력 직후 통일했는가."),
        bullet("복구: 백트래킹에서 선택/해제 쌍이 정확히 대응되는가."),
        bullet("visited 시점: push 시점 방문 처리인지 pop 시점 처리인지 한 가지로 고정했는가."),
        bullet("동시성: 한 칸 변경이 같은 턴의 다른 계산에 즉시 영향을 주지 않는가."),
        bullet("탈출: while/재귀 종료 조건이 보장되는가."),
        h2("4) 시간 배분 전략 (시험용)"),
        bullet("0~20분: 문제 모델링 + 상태 정의 + 반례 2개 메모"),
        bullet("20~90분: 템플릿 기반 1차 구현, 동작 우선"),
        bullet("90~120분: 반례 디버깅, 경계 조건 확정"),
        bullet("120~끝: 최적화와 코드 정리, 출력 포맷 재검증"),
    ]


def append_children(block_id: str, children: list[dict[str, Any]]) -> None:
    for i in range(0, len(children), 40):
        chunk = children[i : i + 40]
        api_request("PATCH", f"/blocks/{block_id}/children", {"children": chunk})
        time.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Review and optionally boost '삼성 A형 템플릿 요약 (암기용 Codex)' page."
    )
    parser.add_argument("--title", default=TARGET_TITLE)
    parser.add_argument("--apply-boost", action="store_true")
    args = parser.parse_args()

    page = find_page_by_title(args.title)
    page_id = page["id"]
    blocks = fetch_all_children(page_id)
    text = flatten_text(blocks)
    score, met, missing = score_page(text)

    print(f"[PAGE] {extract_title(page)}")
    print(f"[ID] {page_id}")
    print(f"[SCORE] {score}/100")
    print(f"[MET] {', '.join(met) if met else '-'}")
    print(f"[MISSING] {', '.join(missing) if missing else '-'}")

    if score < 80:
        print("[JUDGMENT] 현재 상태만으로는 A형 합격용 단일 페이지로 부족 가능성이 큽니다.")
    else:
        print("[JUDGMENT] 핵심 축은 갖춰져 있지만, 실전 구현 템플릿 보강을 권장합니다.")

    if args.apply_boost:
        boost = build_boost_blocks()
        append_children(page_id, boost)
        print(f"[UPDATED] Added {len(boost)} boost blocks.")
    else:
        print("[DRY] No changes applied. Use --apply-boost to append reinforcement blocks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
