# CLAUDE.md - Claude Code 영구 컨텍스트

## 3모델 토론 접근 방법

3모델 독립 토론은 **실제 AI 모델 3개**를 사용한다. API key가 아니라 **CLI 도구**로 접근:

| 모델 | CLI | 실행 방법 |
|---|---|---|
| **GPT-5.4** | `codex` (Codex CLI) | `scripts/delegate_to_codex.sh` 또는 `scripts/run_codex_exec.sh` |
| **Gemini 3.1 Pro** | `gemini` (Gemini CLI) | `scripts/delegate_to_gemini.sh` 또는 `scripts/run_gemini_prompt.sh` |
| **Claude Opus** | 현재 세션 (본인) | 직접 분석 |

### 토론 프로토콜: MAD (Multi-Agent Debate)

학술 기반 MAD 프레임워크를 사용한다 (ref: Liang et al. "Multi-Agents Debate").

**역할 배정:**
- **Advocate (찬성측)**: GPT-5.4 — 최적 설정을 강하게 주장, 정량적 근거 제시
- **Devil's Advocate (반대측)**: Gemini 3.1 Pro — 찬성측 공격, 오버피팅/리스크/비용 약점 지적
- **Judge (심판)**: Claude Opus — 양측 논거 평가, 합의 도출, 최종 판정

**라운드 구조:**
```
Round 1: 독립 주장 (3모델 동시)
  - GPT-5.4: 자신의 최적안 제시 + 근거
  - Gemini 3.1 Pro: 자신의 최적안 제시 + 근거
  - Claude Opus: 자신의 최적안 제시 + 근거

Round 2: 교차 비평 (각 모델이 다른 2모델의 주장을 공격)
  - GPT-5.4: Gemini와 Claude 주장의 약점 지적
  - Gemini: GPT와 Claude 주장의 약점 지적
  - Claude: GPT와 Gemini 주장의 약점 지적

Round 3: 방어 + 수정 (비평을 받고 자기 주장 수정/방어)
  - GPT-5.4: 받은 비평에 대응, 필요시 주장 수정
  - Gemini: 받은 비평에 대응, 필요시 주장 수정
  - Claude: 받은 비평에 대응, 필요시 주장 수정

Round 4: 합의 도출 (3모델 동시)
  - 각 모델이 최종 수정안 + 다른 모델과의 합의점/분쟁점 정리
  - 3모델 투표: 최종 추천 1개 선정
  - 신뢰도 점수(0-100) 각 모델이 독립 부여 → 평균
```

**핵심 원칙:**
- 각 모델은 이전 모델의 출력을 보고 응답 (adversarial chain)
- Devil's Advocate는 반드시 약점을 찾아야 함 (동의 금지)
- Judge는 중립적이며 정량적 근거로만 판정
- 최종 결과에 신뢰도 점수(0-100) 필수

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
