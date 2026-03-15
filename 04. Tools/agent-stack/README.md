# Agent Stack

카카오 링크로 모아둔 레퍼런스를 **지금 이 컴퓨터에서 Codex/OpenClaw가 바로 참조할 수 있는 로컬 도구 스택**으로 정리한 디렉터리입니다.

## 들어있는 것

- `repos.json` — 추적 중인 링크/레포 목록
- `repos/` — GitHub 레포 로컬 체크아웃 위치
- `docs/catalog.md` — 뭐가 왜 유용한지 정리한 카탈로그
- `docs/integration-notes.md` — 바로 적용할 아이디어 메모
- `scripts/agent_stack_sync.sh` — GitHub 레포 clone/pull
- `scripts/codex_agent_stack.sh` — 특정 레포를 작업 디렉터리로 Codex에 바로 질의

## 빠른 사용법

### 1) 레포 동기화

```bash
scripts/agent_stack_sync.sh
```

### 2) Codex로 특정 레포 바로 분석

```bash
scripts/codex_agent_stack.sh agency-agents "Summarize the orchestration model and suggest how to adapt it for OpenClaw."
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

## 메모

웹 링크(`Obsidian Clipper`, `GPters AutoResearch 글`)는 레포가 아니라 참고 문서라 별도 로컬 clone 대상은 아닙니다.
