import argparse
import time
import sys
from pathlib import Path
from typing import Any

import requests

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from notion_automation.core.notion_env import get_notion_token

NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"
STEP_ROOT = Path("gitp/A형준비/bfs")


def notion_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_notion_token()}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def api_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    last_err: str | None = None
    for attempt in range(1, 6):
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=notion_headers(),
                json=payload,
                timeout=30,
            )
            if response.status_code in (429, 500, 502, 503, 504):
                last_err = f"{response.status_code}: {response.text}"
                time.sleep(min(2**attempt, 8))
                continue
            response.raise_for_status()
            if not response.text:
                return {}
            return response.json()
        except requests.RequestException as exc:
            last_err = str(exc)
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"Notion API failed ({method} {path}): {last_err}")


def chunk_text(text: str, size: int = 1600) -> list[str]:
    if len(text) <= size:
        return [text]
    out: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            split = text.rfind("\n", start, end)
            if split > start + 200:
                end = split
        out.append(text[start:end].strip())
        start = end
    return [x for x in out if x]


def title_block(text: str, level: int = 2) -> dict[str, Any]:
    t = f"heading_{level}"
    return {
        "object": "block",
        "type": t,
        t: {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def paragraph_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def bullet_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def todo_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"checked": False, "rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def callout_block(text: str, emoji: str = "🧠") -> dict[str, Any]:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": emoji},
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def code_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "code",
        "code": {
            "language": "python",
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }


def detect_topics(code: str) -> list[str]:
    lower = code.lower()
    rules = [
        ("다익스트라/최단거리", ("heapq", "distance", "dijkstra")),
        ("위상정렬", ("indegree", "topology", "deque")),
        ("이분탐색/파라메트릭 서치", ("left", "right", "mid", "while left <= right")),
        ("DP", ("dp", "memo", "cache")),
        ("그래프 BFS", ("deque", "popleft", "append")),
        ("그래프 DFS/백트래킹", ("dfs", "recursion", "backtrack")),
        ("그리디", ("sort", "greedy", "reverse")),
        ("누적합/투포인터", ("prefix", "acc", "two", "window")),
        ("힙/우선순위큐", ("heapq", "heappush", "heappop")),
    ]
    matched: list[str] = []
    for label, keywords in rules:
        for kw in keywords:
            if kw in lower:
                matched.append(label)
                break
    if not matched:
        matched.append("기본 구현/자료구조")
    return list(dict.fromkeys(matched))


def complexity_hint(topics: list[str], code: str) -> str:
    n_loop = code.count("for ")
    if any("다익스트라" in t for t in topics):
        return "보통 O((V+E) log V). 우선순위큐의 push/pop 횟수와 간선 수를 같이 보세요."
    if any("이분탐색" in t for t in topics):
        return "보통 O(N log X). 판별 함수(check)의 선형 복잡도와 탐색 구간 길이를 분리해 기억하세요."
    if any("DP" in t for t in topics):
        return "상태 수 × 상태 전이 수로 계산하세요. 1차원/2차원 상태 정의를 먼저 고정하세요."
    if any("BFS" in t for t in topics):
        return "정점/칸마다 최대 1회 방문이면 O(V+E) 또는 O(NM)입니다."
    if any("DFS" in t for t in topics):
        return "완전탐색이면 가지치기 전/후 복잡도를 분리해서 봐야 합니다."
    return f"코드상 반복문 출현 횟수는 {n_loop}회입니다. 입력 상한과 함께 실제 상수 계수를 체크하세요."


def build_problem_blocks(step_name: str, file_path: Path, code: str) -> list[dict[str, Any]]:
    topics = detect_topics(code)
    problem_no = file_path.stem
    rel = file_path.as_posix()
    lines = code.splitlines()
    snippet = "\n".join(lines[: min(120, len(lines))]) if lines else ""
    if not snippet.strip():
        snippet = "# Empty file"

    blocks: list[dict[str, Any]] = []
    blocks.append(title_block(f"{problem_no} 풀이 노트", 1))
    blocks.append(callout_block(f"{step_name} / {rel} 기반 자동 분석 노트입니다. 외우기보다 '재현 가능한 로직'을 목표로 구성했습니다."))

    blocks.append(title_block("1) 문제-로직 포지셔닝", 2))
    blocks.append(bullet_block(f"파일: {rel}"))
    blocks.append(bullet_block(f"분류 추정: {', '.join(topics)}"))
    blocks.append(bullet_block("유사 문제에서 먼저 '입력 크기'와 '요구 출력(최솟값/경로/가능여부)'을 고정한 뒤 접근하세요."))
    blocks.append(bullet_block("코드를 외우는 순서는 자료구조 선택 -> 상태 정의 -> 전이/탐색 순서 -> 종료 조건입니다."))

    blocks.append(title_block("2) 암기용 핵심 로직 프레임", 2))
    blocks.append(paragraph_block("아래 프레임은 같은 유형 문제를 처음 봤을 때 60초 내로 설계하기 위한 체크리스트입니다."))
    blocks.append(todo_block("문제 목표를 한 문장으로 재서술한다. (무엇을 최소/최대/판별하는지)"))
    blocks.append(todo_block("상태(state)를 정한다. (노드, 인덱스, 좌표, 비용, 방문 여부)"))
    blocks.append(todo_block("상태 전이 규칙을 적는다. (다음 상태 후보 생성)"))
    blocks.append(todo_block("중복 계산/중복 방문 제거 전략을 정한다. (visited / dp / pruning)"))
    blocks.append(todo_block("종료 조건과 정답 갱신 시점을 분리한다."))
    blocks.append(todo_block("복잡도 상한이 입력 조건을 통과하는지 마지막에 계산한다."))

    blocks.append(title_block("3) 유사문제 대응법 (응용)", 2))
    blocks.append(bullet_block("조건이 '최소 시간/거리'면 BFS 또는 다익스트라를 우선 검토합니다."))
    blocks.append(bullet_block("조건이 '가능한 값의 최댓값/최솟값'이고 판별 가능하면 파라메트릭 서치를 검토합니다."))
    blocks.append(bullet_block("경우의 수 전수 조사에서 N이 작으면 DFS/백트래킹 + 가지치기를 우선 적용합니다."))
    blocks.append(bullet_block("순서 의존 누적 최적화는 DP 상태 정의를 먼저 고정합니다."))
    blocks.append(bullet_block("여러 조건이 섞이면 '그래프화 가능 여부'를 먼저 판단해 모델을 단순화합니다."))
    blocks.append(paragraph_block(complexity_hint(topics, code)))

    blocks.append(title_block("4) 패턴 트리거 맵", 2))
    blocks.append(paragraph_block("문제 문장에서 보이는 단서를 패턴으로 즉시 매핑하는 훈련용 표기입니다."))
    blocks.append(bullet_block("단서: '최단' + 가중치 없음 -> 패턴: BFS + 레벨/거리 배열"))
    blocks.append(bullet_block("단서: '최소 비용' + 가중치 양수 -> 패턴: 다익스트라 + 우선순위큐"))
    blocks.append(bullet_block("단서: '가능한 최대값/최솟값' + 판별 가능 -> 패턴: 파라메트릭 서치"))
    blocks.append(bullet_block("단서: '경우의 수 완전탐색' + N 작음 -> 패턴: DFS/백트래킹 + 가지치기"))
    blocks.append(bullet_block("단서: '순서 의존 최적값 누적' -> 패턴: DP 상태 정의 후 전이식"))

    blocks.append(title_block("5) 실수 방지 포인트", 2))
    blocks.append(todo_block("인덱스 범위(0-based/1-based)와 입력 파싱을 분리해서 검증"))
    blocks.append(todo_block("초기값(INF, -INF, base case) 누락 여부 확인"))
    blocks.append(todo_block("visited 갱신 시점이 push 직후인지 pop 직후인지 일관성 확인"))
    blocks.append(todo_block("정답 갱신 위치가 종료 조건과 충돌하지 않는지 확인"))
    blocks.append(todo_block("디버깅용 소형 반례 3개를 직접 만든 뒤 통과 확인"))

    blocks.append(title_block("6) 능동 회상 Q/A", 2))
    blocks.append(todo_block("Q: 이 문제의 상태(state)는 무엇인가? A: 좌표/노드/인덱스/비용 중 무엇을 묶어야 하는가"))
    blocks.append(todo_block("Q: 중복 방문/중복 계산을 어떻게 제거하는가? A: visited 또는 dp 정의"))
    blocks.append(todo_block("Q: 정답 갱신은 어디서 해야 안전한가? A: 종료 조건 충족 직후"))
    blocks.append(todo_block("Q: 이 코드의 최악 복잡도는? A: 상태 수 × 전이 수로 계산"))
    blocks.append(todo_block("Q: 비슷한 문제로 바뀌면 유지되는 부분과 교체되는 부분은?"))

    blocks.append(title_block("7) 빈칸 복원 스켈레톤", 2))
    blocks.append(code_block("\n".join([
        "# 1) 입력 파싱",
        "# 2) 핵심 자료구조 초기화 (graph/board/dp/visited)",
        "# 3) 상태 전이 함수 정의 (dfs/bfs/relax/check)",
        "# 4) 반복/탐색 루프",
        "# 5) 정답 갱신",
        "# 6) 출력",
    ])))

    blocks.append(title_block("8) 코드 원문 + 재해석", 2))
    blocks.append(paragraph_block("원문 코드의 첫 부분을 첨부합니다. 필요한 경우 이 페이지 하단에 직접 반례와 수정 버전을 덧붙이세요."))
    for part in chunk_text(snippet, size=1500):
        blocks.append(code_block(part))

    blocks.append(title_block("9) 반복학습 루틴", 2))
    blocks.append(bullet_block("Day 1: 코드 안 보고 의사코드 작성"))
    blocks.append(bullet_block("Day 3: 유사 문제 1개에 같은 틀로 적용"))
    blocks.append(bullet_block("Day 7: 시간복잡도/실수포인트만 보고 전체 재구성"))
    blocks.append(bullet_block("Day 14: 빈칸 스켈레톤만 보고 15분 내 전체 코드 복원"))
    blocks.append(bullet_block("Day 30: 랜덤 3문제에서 트리거 맵으로 접근법만 먼저 구두 설명"))
    blocks.append(callout_block("이 페이지를 기반으로 '다음에 처음 보는 문제를 어떻게 풀지'를 말로 설명할 수 있어야 암기 완료입니다.", "✅"))
    return blocks


def append_children(block_id: str, children: list[dict[str, Any]]) -> None:
    for i in range(0, len(children), 40):
        chunk = children[i : i + 40]
        api_request("PATCH", f"/blocks/{block_id}/children", {"children": chunk})
        time.sleep(0.2)


def create_page(parent: dict[str, Any], title: str) -> dict[str, Any]:
    payload = {
        "parent": parent,
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title[:200]}}],
            }
        },
    }
    return api_request("POST", "/pages", payload)


def collect_files() -> list[Path]:
    files = sorted(STEP_ROOT.rglob("*.py"))
    return [f for f in files if "__pycache__" not in f.parts]


def step_key(file_path: Path) -> str:
    try:
        rel = file_path.relative_to(STEP_ROOT)
    except ValueError:
        return "Ungrouped"
    if len(rel.parts) >= 2 and rel.parts[0].startswith("Step"):
        return rel.parts[0]
    return "Ungrouped"


def publish_all(root_title: str, parent_page_id: str, dry_run: bool = False) -> None:
    files = collect_files()
    if not files:
        raise RuntimeError(f"No Python files found under {STEP_ROOT}")

    step_map: dict[str, list[Path]] = {}
    for f in files:
        step_map.setdefault(step_key(f), []).append(f)

    print(f"[INFO] files={len(files)}, steps={len(step_map)}")
    for step, items in sorted(step_map.items()):
        print(f"  - {step}: {len(items)} files")

    if dry_run:
        return

    root_page = create_page({"type": "page_id", "page_id": parent_page_id}, root_title)
    root_id = root_page["id"]
    print(f"[INFO] root page created: {root_id}")

    intro = [
        title_block("A형 준비 전체 자동 정리", 1),
        callout_block("Step별/문제별로 분리된 암기+응용 중심 노트입니다. 각 페이지는 코드 원문, 핵심 로직, 실수 포인트, 유사문제 대응 프레임을 포함합니다."),
        bullet_block(f"총 문제 수: {len(files)}"),
        bullet_block("구성 기준: Step 분류 -> 문제별 페이지"),
        bullet_block("학습 원칙: 코드 암기가 아니라 로직 재현 능력 확보"),
    ]
    append_children(root_id, intro)

    created_problem_pages = 0
    for step, items in sorted(step_map.items()):
        step_page = create_page({"type": "page_id", "page_id": root_id}, f"{step} 정리")
        step_id = step_page["id"]
        append_children(
            step_id,
            [
                title_block(f"{step} 학습 개요", 1),
                paragraph_block("이 Step 페이지 아래에 각 문제별 상세 노트를 분리했습니다."),
                bullet_block(f"문제 수: {len(items)}"),
                bullet_block("권장 루틴: 쉬운 문제 1회독 -> 어려운 문제 2회독 -> 랜덤 셔플 복기"),
            ],
        )

        for file_path in items:
            code = file_path.read_text(encoding="utf-8", errors="replace")
            prob_title = f"{file_path.stem} - {', '.join(detect_topics(code)[:2])}"
            page = create_page({"type": "page_id", "page_id": step_id}, prob_title)
            blocks = build_problem_blocks(step, file_path, code)
            append_children(page["id"], blocks)
            created_problem_pages += 1
            print(f"[OK] {step} / {file_path.name}")
            time.sleep(0.15)

    print(f"[DONE] created problem pages: {created_problem_pages}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish full A-type study notes to Notion")
    parser.add_argument(
        "--root-title",
        default=f"A형 준비 전체 정리 (Auto {time.strftime('%Y-%m-%d %H:%M')})",
        help="Root page title in Notion",
    )
    parser.add_argument(
        "--parent-page-id",
        default="2e7eacc8-175a-8035-8d30-ca6bf5e1c524",
        help="Notion parent page id where root page will be created",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    publish_all(root_title=args.root_title, parent_page_id=args.parent_page_id, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
