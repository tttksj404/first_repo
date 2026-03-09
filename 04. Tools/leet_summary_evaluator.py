import os
import sys
import argparse
import requests
from pathlib import Path

def get_api_key():
    # .env 파일들에서 GOOGLE_API_KEY를 찾습니다.
    env_paths = [Path('.env'), Path('notion_automation/.env.notion')]
    for path in env_paths:
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                if line.strip().startswith('GOOGLE_API_KEY='):
                    return line.split('=', 1)[1].strip().strip('"\'')
    return os.environ.get('GOOGLE_API_KEY')

def call_gemini(prompt, api_key, model="gemini-3.1-pro-preview"):
    # 최고 성능 모델인 gemini-3.1-pro-preview를 기본으로 사용합니다.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2, # 논리적이고 일관된 평가를 위해 낮게 설정
        }
    }
    response = requests.post(url, headers=headers, json=data)
    
    if response.status_code != 200:
        # 3.1이 없거나 에러날 경우 2.5-pro로 Fallback
        if model == "gemini-3.1-pro-preview":
            print(f"⚠️ {model} 호출 실패, gemini-2.5-pro로 재시도합니다...")
            return call_gemini(prompt, api_key, model="gemini-2.5-pro")
        else:
            print(f"❌ API Error ({response.status_code}): {response.text}")
            sys.exit(1)
            
    return response.json()['candidates'][0]['content']['parts'][0]['text']

def main():
    parser = argparse.ArgumentParser(description="LEET 요약본 검증 및 기반 문제 풀이 시뮬레이터")
    parser.add_argument("folder", help="원문(passage.txt), 요약본(summary.txt), 문제(questions.txt)가 있는 폴더 경로")
    args = parser.parse_args()

    folder = Path(args.folder)
    passage_file = folder / "passage.txt"
    summary_file = folder / "summary.txt"
    questions_file = folder / "questions.txt"

    if not passage_file.exists() or not summary_file.exists() or not questions_file.exists():
        print(f"❌ '{folder}' 폴더 내에 필수 파일이 부족합니다.")
        print(f"준비해야 할 파일: passage.txt (원문), summary.txt (본인의 요약), questions.txt (문제)")
        sys.exit(1)

    passage = passage_file.read_text(encoding='utf-8')
    summary = summary_file.read_text(encoding='utf-8')
    questions = questions_file.read_text(encoding='utf-8')

    api_key = get_api_key()
    if not api_key:
        print("❌ GOOGLE_API_KEY를 찾을 수 없습니다. .env 파일에 설정해주세요.")
        sys.exit(1)

    print(f"\n🚀 LEET 요약 검증 시스템을 시작합니다... (대상: {folder.name})\n")

    # [Step 1] 요약본 정밀 평가
    print("🔍 [1/2] 요약본 정밀 분석 중 (원문 vs 요약본 대조)...")
    prompt_eval = f"""당신은 LEET(법학적성시험) 언어이해 최고 수준의 전문 강사입니다.
사용자님은 '대립항', '범주화', '공차관계', '단어 질감들'을 중시하는 고도화된 구조적 독해법을 연습 중입니다.

다음은 언어이해 기출 원문(Passage)과 학생이 작성한 문단별 요약본(Summary)입니다.

[원문]
{passage}

[학생의 요약본]
{summary}

학생의 요약본을 매우 엄격하게 평가해주세요:
1. ⚖️ **구조적 독해 파악**: 원문의 핵심 대립항(Antithesis)과 범주화(Categorization)가 요약본에 선명하게 잡혀 있는가?
2. 🚨 **정보 누락 및 왜곡**: 문제를 푸는 데 결정적인 단서(예: 예외 조건, 인과 관계, 특수한 단어 질감)가 요약에서 누락되지 않았는가?
3. 🔗 **문단 연계**: 개별 문단을 넘어 전체 글의 흐름과 거시적 구조가 요약본에 잘 담겨 있는가?

마크다운 형식으로, 학생이 자신의 약점을 정확히 파악할 수 있도록 날카롭고 구체적으로 피드백해주세요.
"""
    eval_result = call_gemini(prompt_eval, api_key)
    
    # [Step 2] 요약본 기반 블라인드 문제 풀이
    print("🧠 [2/2] 요약본 기반 블라인드 문제 풀이 시뮬레이션 중...")
    prompt_solve = f"""당신은 LEET 수험생입니다. 당신은 원문을 읽지 못했으며, 오직 아래에 제공된 [학생의 요약본]만 읽고 3개의 기출문제를 풀어야 합니다.

[학생의 요약본]
{summary}

[기출 문제]
{questions}

이 테스트의 목적은 '학생의 요약본이 문제를 풀기에 충분한 정보를 담고 있는지' 검증하는 것입니다.
각 문제에 대해 다음을 엄격히 수행하세요:
1. 오직 [학생의 요약본]에 있는 정보만을 근거로 각 선지의 참/거짓을 판별하세요. AI의 외부 지식이나 상식은 절대 개입하면 안 됩니다.
2. 🚨 만약 [학생의 요약본]에 특정 선지를 판단할 정보가 아예 없다면, 억지로 추론하지 말고 **"❌ 판단 불가 (요약본 정보 누락: ~에 대한 내용이 없음)"** 이라고 명시하세요.
3. 최종적으로 요약본만으로 도출할 수 있는 정답을 제시하세요. (정보 부족으로 정답 도출이 불가능하다면 불가능하다고 선언하세요.)

각 문제별로 선지 분석과 최종 결론을 마크다운으로 깔끔하게 작성해주세요.
"""
    solve_result = call_gemini(prompt_solve, api_key)

    # 리포트 파일 생성
    report_file = folder / "evaluation_report.md"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("# 📊 LEET 요약 및 문제풀이 검증 리포트\n\n")
        f.write("## 🔍 1. 요약본 정밀 평가 (전문 강사 피드백)\n")
        f.write(eval_result + "\n\n---\n\n")
        f.write("## 🧠 2. 요약본 기반 블라인드 문제 풀이 시뮬레이션\n")
        f.write("> 💡 이 파트는 AI가 **원문을 보지 않고 오직 학생의 요약본만으로** 문제를 푼 결과입니다.\n")
        f.write("> 선지 분석 중 **'판단 불가'**가 나온 항목은 요약 과정에서 놓친 핵심 정보(구멍)를 의미합니다.\n\n")
        f.write(solve_result + "\n")

    print(f"\n✅ 검증 완료! 완벽한 피드백 리포트가 생성되었습니다.")
    print(f"📄 리포트 확인: {report_file}")

if __name__ == '__main__':
    main()
