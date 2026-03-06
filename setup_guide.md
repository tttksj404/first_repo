# 🚀 Gemini CLI & OpenAI Codex 환경 복구 가이드 (2026-03-06)

이 가이드는 현재 컴퓨터의 모든 AI 개발 및 노션 자동화 환경을 다른 컴퓨터로 100% 이전하기 위한 절차를 담고 있습니다.

## 1. 필수 시스템 소프트웨어 설치
가장 먼저 아래의 도구들을 설치해야 합니다.
- **Python (3.10+):** [python.org](https://www.python.org/) (설치 시 'Add Python to PATH' 필수)
- **Node.js (LTS):** [nodejs.org](https://nodejs.org/) (npm 포함)
- **Git:** [git-scm.com](https://git-scm.com/) (CLI 및 Bash 환경 제공)

## 2. Gemini CLI 설치 및 메모리 복구
- **글로벌 설치:** `npm install -g @google/gemini-cli`
- **메모리(기억) 동기화:** 
  - 현재 프로젝트의 `.gemini/gemini.md` 파일 내용을 복사합니다.
  - 새 환경에서 Gemini 실행 후 `save_memory`를 통해 핵심 원칙들을 재등록하거나, `C:\Users\<USER>\AppData\Roaming\npm\node_modules\@google\gemini-cli\node_modules\@google\gemini-cli-core\dist\src\memory\global_memory.md` 경로에 직접 덮어씁니다.

## 3. OpenAI Codex (OpenAI API) 설정
현재 프로젝트는 `npx @openai/codex`를 통해 고성능 모델(Codex)을 사용합니다.
- **API 키 등록:** 
  - `.env` 파일에 `OPENAI_API_KEY=sk-...`를 작성합니다.
  - 또는 `npx @openai/codex login`을 실행하여 인증합니다.
- **`codex` 명령어 설정 (Windows):**
  - 프로젝트 루트의 `codex` 파일은 Bash 스크립트입니다.
  - Windows PowerShell에서 직접 사용하려면 `codex.cmd` 파일을 아래 내용으로 생성하세요:
    ```cmd
    @echo off
    npx @openai/codex %*
    ```

## 4. 환경 변수 및 비밀 키 (.env)
`.gitignore`에 의해 제외된 아래 파일들을 수동으로 생성하거나 백업에서 복구해야 합니다.
- **위치:** `C:\Users\SSAFY\Desktop\first_repo\.env`
- **필수 항목:**
  ```env
  GOOGLE_API_KEY=YOUR_GEMINI_KEY
  OPENAI_API_KEY=YOUR_OPENAI_KEY
  NOTION_TOKEN=secret_your_notion_token
  ```

## 5. 파이썬 의존성 및 노션 자동화 도구
- **의존성 설치:**
  ```powershell
  cd C:\Users\SSAFY\Desktop\first_repo
  pip install requests python-dotenv
  ```
- **노션 자동화:** `notion_automation` 폴더 내의 스크립트들은 `requests`를 직접 제어하며, `04. Tools\sitecustomize.py`를 통해 라이브러리 경로가 자동 관리됩니다.

## 6. 협업 도구 (`ai_collab_cli.py`) 사용법
Gemini와 Codex를 동시에 사용하여 검증하는 도구입니다.
- **실행:** `python "04. Tools\ai_collab_cli.py" --prompt "내용"`
- **체크사항:** `--gemini-cmd`와 `--codex-cmd`가 시스템 PATH에 등록되어 있거나 현재 경로에 있어야 합니다.

## 7. 최우선 준수 원칙 (Memories)
환경 이전 후 첫 프롬프트로 다음을 입력하여 AI의 페르소나를 고정하세요:
> "새 컴퓨터로 이전 완료. `.gemini/gemini.md`의 **[절대 원칙]**, **[노션 자동화 절대 표준 지침]**, **[2중 청킹 프로토콜]**을 확인해. 특히 삼성 A형 알고리즘 해설 시 **'IM 정리'** 수준의 극한의 상세함과 **전체 정답 코드**를 포함하는 것을 잊지 마."

---
**작성일:** 2026-03-06
**대상 프로젝트:** `first_repo` (Gemini CLI / OpenAI Codex / Notion Automation)
