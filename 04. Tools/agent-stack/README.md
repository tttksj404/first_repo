# Agent Stack

카카오 링크로 모아둔 레퍼런스를 **지금 이 컴퓨터에서 Codex/OpenClaw가 바로 참조할 수 있는 로컬 도구 스택**으로 정리한 디렉터리입니다.

## 들어있는 것

- `repos.json` — 추적 중인 링크/레포 목록
- `repos/` — GitHub 레포 로컬 체크아웃 위치
- `docs/catalog.md` — 뭐가 왜 유용한지 정리한 카탈로그
- `docs/integration-notes.md` — 바로 적용할 아이디어 메모
- `docs/nl-routing-registry.md` — Telegram/OpenClaw 요청을 intent/skill/repo로 매핑하는 레지스트리
- `scripts/agent_stack_sync.sh` — GitHub 레포 clone/pull
- `scripts/codex_agent_stack.sh` — 특정 레포를 작업 디렉터리로 Codex에 바로 질의
- `scripts/nl_route.py` — 자연어 요청을 로컬 skill/repo/실행 경로로 분류하는 라우터
- `scripts/nl_dispatch.py` — 라우팅 결과를 바탕으로 direct action plan 또는 Codex 위임까지 이어주는 세미 자동 디스패처

## 빠른 사용법

### 1) 레포 동기화

```bash
scripts/agent_stack_sync.sh
```

### 2) Codex로 특정 레포 바로 분석

```bash
scripts/codex_agent_stack.sh agency-agents "Summarize the orchestration model and suggest how to adapt it for OpenClaw."
```

### 3) Telegram/OpenClaw 요청 라우팅

```bash
python3 "04. Tools/agent-stack/scripts/nl_route.py" \
  "Summarize these daemon logs and tell me the latest real failure."
```

기본 출력은 JSON이다. 포함 항목:
- `intent_id`
- `why_it_matched`
- `recommended_skills`
- `recommended_repos`
- `handle_via`
- `execution_path`

추가 옵션:
- `--list-intents` — 등록된 intent 목록 확인
- `--format text` — 사람이 읽기 쉬운 텍스트 출력

### 4) 반자동 dispatcher로 direct/delegate 결정

기본값은 dry-run이다. delegate intent면 어떤 repo를 고르고 어떤 Codex wrapper 명령을 실행할지 보여주고, direct intent면 바로 처리용 compact action plan을 출력한다.

```bash
python3 "04. Tools/agent-stack/scripts/nl_dispatch.py" \
  "Route Telegram requests across planner, executor, and verifier agents."
```

JSON으로 보고 싶으면:

```bash
python3 "04. Tools/agent-stack/scripts/nl_dispatch.py" \
  --format json \
  "Route Telegram requests across planner, executor, and verifier agents."
```

실제로 wrapper를 실행하려면 `--run`:

```bash
python3 "04. Tools/agent-stack/scripts/nl_dispatch.py" \
  --run \
  "Route Telegram requests across planner, executor, and verifier agents."
```

direct route 예시:

```bash
python3 "04. Tools/agent-stack/scripts/nl_dispatch.py" \
  "Summarize these daemon logs and tell me the latest real failure."
```

가능한 repo id:
- `agency-agents`
- `autoresearch`
- `dot-studio`
- `onecli`
- `dgk-gpt`
- `awesome-openclaw-usecases`
- `symphony`
- `obsidian-code`

## 바로 적용 추천

### OpenClaw/Codex 운영 개선
- `agency-agents`
- `symphony`
- `awesome-openclaw-usecases`

예시 질문:
- "OpenClaw에 맞는 planner/executor/verifier 패턴으로 정리해줘"
- "최신 명령 우선 처리되게 하려면 어떤 state handoff가 필요한지 설명해줘"

### 반복 조사/실험 루프
- `autoresearch`
- GPters AutoResearch 글

예시 질문:
- "이 구조를 Telegram 기반 overnight research loop로 줄여줘"
- "우리 리포의 quant_autoresearch와 비교해서 차이점 정리해줘"

### Obsidian 수집/정리
- `obsidian-code`
- `Obsidian Clipper`

예시 질문:
- "Obsidian 코드 워크플로우를 내 vault 구조에 맞게 적용안 작성해줘"

### 운영 라우팅 intent
- `obsidian_note_work`
- `openclaw_orchestration_ideas`
- `quant_autoresearch`
- `security_secrets`
- `code_review_commit_hygiene`
- `logs_debugging`
- `long_running_work_tracking`

## 메모

웹 링크(`Obsidian Clipper`, `GPters AutoResearch 글`)는 레포가 아니라 참고 문서라 별도 로컬 clone 대상은 아닙니다.
