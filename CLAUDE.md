# CLAUDE.md - Claude Code 영구 컨텍스트

## 3모델 토론 접근 방법

3모델 독립 토론은 **실제 AI 모델 3개**를 사용한다. API key가 아니라 **CLI 도구**로 접근:

| 모델 | CLI | 실행 방법 |
|---|---|---|
| **GPT-5.4** | `codex` (Codex CLI) | `scripts/delegate_to_codex.sh` 또는 `scripts/run_codex_exec.sh` |
| **Gemini 3.1 Pro** | `gemini` (Gemini CLI) | `scripts/delegate_to_gemini.sh` 또는 `scripts/run_gemini_prompt.sh` |
| **Claude Opus** | 현재 세션 (본인) | 직접 분석 |

### 토론 프로세스
1. 백테스트 결과 데이터를 준비
2. 각 모델에 동일한 데이터 + 프롬프트를 전달 (독립 평가)
3. 3개 모델의 응답을 수집
4. 교차 검증 → 합의(consensus) 도출

### CLI 경로 (로컬 환경)
- `codex`: `/Users/tttksj/.npm-global/bin/codex`
- `gemini`: `/usr/local/bin/gemini`
- 래퍼 스크립트: `scripts/delegate_to_codex.sh`, `scripts/delegate_to_gemini.sh`

### 주의사항
- API key 방식이 아님. CLI 도구를 직접 호출할 것
- 원격 세션(Claude Code Web)에서는 CLI 사용 불가 → 로컬 환경에서 실행 필요
- 3모델 토론 요청 시 절대 스코어링 함수로 대체하지 말 것
