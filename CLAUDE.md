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

### 실행 방법

#### 로컬 환경 (codex/gemini CLI 사용 가능)
```bash
./scripts/run_ensemble_3model_debate.sh
```
DOT Studio Bridge (`run_sequence.py`)를 통해 자동 실행. 결과: `quant_runtime/output/ensemble_3model_debate.json`

#### 원격 세션 (Claude Code Web — codex/gemini CLI 없음)
원격에서는 egress proxy가 OpenAI/Gemini API를 차단함. 따라서:
1. **Claude Opus**: 현재 세션에서 직접 분석 수행
2. **GPT-5.4 + Gemini**: 프롬프트를 `quant_runtime/output/debate_prompt.txt`에 저장
3. 사용자가 로컬에서 아래 실행:
   ```bash
   codex exec --full-auto "$(cat quant_runtime/output/debate_prompt.txt)" > quant_runtime/output/gpt54_eval.txt
   gemini -p "$(cat quant_runtime/output/debate_prompt.txt)" > quant_runtime/output/gemini_eval.txt
   ```
4. 결과를 세션에 붙여넣으면 Claude가 합의 도출

### CLI 경로 (로컬 환경)
- `codex`: `/Users/tttksj/.npm-global/bin/codex`
- `gemini`: `/usr/local/bin/gemini`
- 래퍼 스크립트: `scripts/delegate_to_codex.sh`, `scripts/delegate_to_gemini.sh`

### 절대 금지사항
- 3모델 토론 요청 시 스코어링 함수로 대체 금지
- Claude가 GPT/Gemini를 흉내내는 것 금지 — 반드시 실제 모델 호출
- API key 방식 시도 금지 — CLI 도구 사용
