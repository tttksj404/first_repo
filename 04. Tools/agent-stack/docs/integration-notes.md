# Integration Notes

## 목적
링크 모음이 그냥 북마크로 죽지 않게, **Codex/OpenClaw가 지금 바로 읽고 활용할 수 있는 재료**로 바꾸는 것.

## 레포별 한 줄 용도
- `agency-agents`: 역할 분리형 멀티 에이전트 구조 참고
- `autoresearch`: 자동 실험/조사 루프 참고
- `dot-studio`: 시각적 오케스트레이션 UI 참고
- `onecli`: 단일 CLI 진입점 설계 참고
- `dgk-gpt`: CLI/에이전트 실험 구조 참고
- `awesome-openclaw-usecases`: OpenClaw 활용 사례 수집
- `symphony`: 작업 분해/협업 설계 참고
- `obsidian-code`: Obsidian 기반 코드 지식관리 참고

## OpenClaw에서 바로 쓰는 패턴
1. repo를 동기화한다.
2. 필요한 repo id를 고른다.
3. `scripts/codex_agent_stack.sh <repo-id> "질문"` 형태로 바로 질의한다.
4. 나온 내용을 현재 리포의 `.agents/skills`, `AGENTS.md`, `scripts/` 개선에 반영한다.

## 추천 첫 질문
### agency-agents
- 역할 분리 규칙만 뽑아서 현재 `AGENTS.md`와 비교
- 최신 명령 우선 처리 규칙 설계

### autoresearch
- 현재 `.agents/skills/quant-autoresearch`와 비교
- overnight automation에 필요한 최소 루프 추리기

### awesome-openclaw-usecases
- Telegram DM 기반 작업 패턴 발췌
- 지금 환경에서 바로 쓸 수 있는 사례만 추리기

### obsidian-code
- 네 vault 구조에 맞는 코드/프롬프트/실험 기록 방식 설계
