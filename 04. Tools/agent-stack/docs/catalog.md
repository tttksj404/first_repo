# Agent Stack Catalog

이 디렉터리는 링크 북마크 모음이 아니라, **Codex/OpenClaw가 바로 참조할 수 있는 로컬 레퍼런스 스택**이다.

## 빠른 결론

### 지금 바로 실용적인 것
- **agency-agents**: 역할별 에이전트 프롬프트/구조 참고용
- **symphony**: 작업 단위 분리, 자율 구현 런 관리 참고용
- **awesome-openclaw-usecases**: OpenClaw 운영 아이디어 수집용
- **autoresearch**: overnight 실험 루프 참고용
- **obsidian-code** + **Obsidian Clipper**: Obsidian 기반 지식 수집/편집 흐름 참고용

### 조심해서 볼 것
- **onecli**: 아이디어는 좋지만 비밀/크리덴셜 계층이라 실제 도입은 보안 검토 후
- **dot-studio**: 시각적 orchestration UI 참고엔 좋지만, 지금 당장 로컬 작업자동화 핵심은 아님
- **dgk-gpt**: Codex 운영 템플릿 참고용으로 유용하지만 그대로 섞기보다 필요한 부분만 차용 추천

---

## Repo / Link Notes

### 1) agency-agents
- URL: https://github.com/msitarzewski/agency-agents
- Local: `04. Tools/agent-stack/repos/agency-agents`
- 핵심: 전문 역할 프롬프트 라이브러리 + OpenClaw integration 문서 포함
- 바로 쓸 포인트:
  - 역할 카탈로그 설계 참고
  - `integrations/openclaw/README.md` 기반으로 OpenClaw agent workspace 변환 아이디어 차용
  - planner / executor / reviewer / reality-checker 류 분리 방식 참고
- 우리 환경 적용 아이디어:
  - `.agents/skills`와 `AGENTS.md`의 역할 분리를 더 선명하게 만들기
  - OpenClaw용 agentId 세분화 실험

### 2) autoresearch
- URL: https://github.com/karpathy/autoresearch
- Local: `04. Tools/agent-stack/repos/autoresearch`
- 핵심: 사람이 Python 코드를 직접 만지는 대신 `program.md`로 연구 조직을 설정하고, 에이전트가 반복 실험 수행
- 바로 쓸 포인트:
  - overnight 실험 루프
  - 실험 keep/discard 판단 구조
  - 인간은 정책/목표를, 에이전트는 탐색/실행을 맡는 분리
- 우리 환경 적용 아이디어:
  - 현재 quant/autoresearch 흐름을 `program.md` 스타일 운영 문서로 명시화
  - Telegram으로 “오늘 밤 이것만 최적화” 식 지시를 내리고 아침에 결과 회수

### 3) dot-studio
- URL: https://github.com/dance-of-tal/dot-studio
- Local: `04. Tools/agent-stack/repos/dot-studio`
- 핵심: Figma 스타일의 시각적 AI orchestration workspace
- 바로 쓸 포인트:
  - 노드/엣지 기반 orchestration UX 참고
  - 시각적 state flow 표현 방식 참고
- 우리 환경 적용 아이디어:
  - 장기적으로 OpenClaw/OMX 상태를 시각화하는 대시보드 발상 참고

### 4) onecli
- URL: https://github.com/onecli/onecli
- Local: `04. Tools/agent-stack/repos/onecli`
- 핵심: 에이전트에게 서비스 접근을 주되 키를 직접 노출하지 않는 credential vault/gateway
- 바로 쓸 포인트:
  - gateway 방식 자격증명 주입 구조
  - container runtime에 proxy/CA 설정을 삽입하는 접근법
- 우리 환경 적용 아이디어:
  - 장기적으로 외부 API를 안전하게 다룰 때 참고
- 주의:
  - 실제 사용은 보안 검토와 운영 복잡도 판단이 먼저

### 5) dgk-gpt
- URL: https://github.com/dgk-dev/dgk-gpt
- Local: `04. Tools/agent-stack/repos/dgk-gpt`
- 핵심: Codex CLI 팀 셋업 배포기
- 바로 쓸 포인트:
  - AGENTS/skills/MCP 기본값 배포 방식
  - 팀 셋업 표준화 패턴
- 우리 환경 적용 아이디어:
  - 현재 repo의 AGENTS/skill 운영을 패키지화할 때 참조

### 6) awesome-openclaw-usecases
- URL: https://github.com/hesamsheikh/awesome-openclaw-usecases
- Local: `04. Tools/agent-stack/repos/awesome-openclaw-usecases`
- 핵심: OpenClaw 실사용 시나리오 모음
- 바로 쓸 포인트:
  - phone-based assistant
  - overnight mini-app builder
  - second brain
  - multi-agent team
- 우리 환경 적용 아이디어:
  - Telegram DM 기반 작업 흐름 고도화
  - Obsidian/second-brain 연동 시나리오 발굴

### 7) symphony
- URL: https://github.com/openai/symphony
- Local: `04. Tools/agent-stack/repos/symphony`
- 핵심: 프로젝트 일을 고립된 autonomous implementation run으로 전환
- 바로 쓸 포인트:
  - 작업 단위를 agent-run으로 격리
  - proof-of-work/검증 결과를 함께 관리
  - 사람은 코드 감시보다 work management에 집중
- 우리 환경 적용 아이디어:
  - 장기 작업을 run 단위 아티팩트로 남기는 구조
  - implement / verify / land 분리 강화

### 8) obsidian-code
- URL: https://github.com/reallygood83/obsidian-code
- Local: `04. Tools/agent-stack/repos/obsidian-code`
- 핵심: Obsidian 안에서 Claude와 대화하며 노트 읽기/쓰기/명령 실행
- 바로 쓸 포인트:
  - vault-centric AI 작업 방식
  - 노트 첨부/핀/권한 모드 UX
- 우리 환경 적용 아이디어:
  - Obsidian 작업을 Telegram/OpenClaw와 어떻게 이어 붙일지 설계 참고

### 9) Obsidian Web Clipper
- URL: https://obsidian.md/clipper
- Local clone 없음
- 핵심: 웹 페이지/하이라이트를 Obsidian으로 빠르게 저장
- 우리 환경 적용 아이디어:
  - 수집은 Clipper, 정리는 OpenClaw/Codex, 보관은 vault

### 10) GPters AutoResearch 글
- URL: https://www.gpters.org/nocode/post/autoresearch-karpathy-automatically-leave-Bk0shiVsTJOzhp8
- Local clone 없음
- 핵심: AutoResearch 컨셉을 한국어로 빠르게 이해하기 좋은 설명 링크

---

## 추천 사용 패턴

### 패턴 A: 레퍼런스 조사
```bash
04.\ Tools/agent-stack/scripts/codex_agent_stack.sh agency-agents "OpenClaw에 맞는 역할 분리 구조만 뽑아줘"
```

### 패턴 B: 현재 repo 설계 비교
```bash
04.\ Tools/agent-stack/scripts/codex_agent_stack.sh symphony "이 repo의 AGENTS.md와 비교했을 때 run isolation 아이디어를 어디에 넣으면 좋은지 정리해줘"
```

### 패턴 C: overnight loop 아이디어 추출
```bash
04.\ Tools/agent-stack/scripts/codex_agent_stack.sh autoresearch "quant runtime에 맞게 overnight experiment loop로 축약해줘"
```

### 패턴 D: Obsidian workflow 설계
```bash
04.\ Tools/agent-stack/scripts/codex_agent_stack.sh obsidian-code "내 Obsidian + Telegram + OpenClaw 조합에 맞는 워크플로우를 설계해줘"
```

---

## 최소 운영 규칙
- 레포 sync: `04. Tools/agent-stack/scripts/agent_stack_sync.sh`
- Codex 질의: `04. Tools/agent-stack/scripts/codex_agent_stack.sh <repo-id> "질문"`
- 실제 코드/운영에 섞기 전에는:
  - 보안 검토
  - 라이선스 확인
  - 현재 repo와의 충돌 범위 확인
