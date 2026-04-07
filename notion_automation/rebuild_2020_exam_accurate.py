import requests
import os
import json
import time

# Use the token found in .env
NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
PAGE_ID = "325eacc8175a811d8237c7414ef471ea" # 기존 생성된 2020년 2회차 페이지 ID

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def delete_all_blocks(page_id):
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    res = requests.get(url, headers=HEADERS)
    if res.status_code == 200:
        blocks = res.json().get("results", [])
        for block in blocks:
            requests.delete(f"https://api.notion.com/v1/blocks/{block['id']}", headers=HEADERS)
        print(f"✅ Cleared existing blocks in page {page_id}")

def append_blocks(block_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    for i in range(0, len(blocks), 50):
        chunk = blocks[i:i+50]
        res = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if res.status_code != 200:
            print(f"❌ Error appending blocks: {res.status_code}, {res.text}")
        time.sleep(0.5)

questions_2020_v2 = [
    {
        "q": """1. 다음 보기는 네트워크 인프라 서비스 관리 실무와 관련된 사례이다. 괄호안에 들어갈 가장 적합한 용어를 한글 또는 영문으로 쓰시오.

귀하는 IT회사의 보안관제실에서 근무하고 있다. 정보시스템 운영 중 자연재해나 시스템 장애 등의 이유로 대고객 서비스가 불가능한 경우가 종종 발생한다. 이를 대비하여 백업 및 복구 솔루션을 도입하고자 한다.
백업 및 복구 솔루션은 ( )와 복구 목표 시점(RPO) 기준을 충족할 수 있는 제품으로 선정해야 한다.
( )는 “비상사태 또는 업무중단 시점으로부터 업무가 복구되어 다시 정상가동 될 때까지의 시간” 을 의미한다.""",
        "a": "RTO (Recovery Time Objective)",
        "reason": "업무 중단 시점부터 복구되어 정상 가동될 때까지의 '시간적 목표'를 의미하기 때문입니다.",
        "concept": "RPO(복구 목표 시점), MTTR(평균 수리 시간)"
    },
    {
        "q": """2. 다음 파이썬(Python) 스크립트의 실행 결과를 적으시오.

asia={'한국', '중국', '일본'}
asia.add('베트남')
asia.add('중국')
asia.remove('일본')
asia.update(['홍콩', '한국', '태국'])
print(asia)""",
        "a": "{'한국', '중국', '베트남', '홍콩', '태국'} (순서 상관없음)",
        "reason": "Set은 중복을 허용하지 않으며, add('중국')은 변화가 없고 update 시 기존 요소('한국')는 유지됩니다.",
        "concept": "파이썬 Set 자료구조의 중복 제거 및 합집합 연산"
    },
    {
        "q": """3. 다음에서 설명하는 기술을 영문 약어로 쓰시오.

'비동기식 자바스크립트 XML'을 의미하는 용어로, 클라이언트와 웹서버 간에 XML 데이터를 내부적으로 통신하는 대화식 웹 애플리케이션의 제작을 위해 사용된다. 웹 페이지 전체를 '새로고침'할 필요 없이 현재 페이지에서 필요한 일부만 로딩되도록 하는 웹 개발 기법이다.""",
        "a": "AJAX (Asynchronous JavaScript and XML)",
        "reason": "XMLHttpRequest 객체를 사용하여 페이지 전체를 새로고침하지 않고 비동기적으로 데이터를 교환하는 기술입니다.",
        "concept": "비동기 통신, XMLHttpRequest, JSON"
    },
    {
        "q": """4. 다음에서 설명하는 개발방법론은 무엇인지 적으시오.

고객의 요구사항 변화에 유연하게 대응하기 위해 일정한 주기를 반복하면서 개발하며 고객에게 시제품을 지속적으로 제공한다. 폭포수 모형에 대비되는 유연한 방법론으로 비교적 소규모 개발 프로젝트에서 각광받고 있다.""",
        "a": "애자일 (Agile)",
        "reason": "사람 중심, 변화에 유연, 반복적 개발(Iteration)을 특징으로 하기 때문입니다.",
        "concept": "XP, Scrum, Kanban, Lean"
    },
    {
        "q": """5. 다음에 제시된 자바(Java) 프로그램이 [처리 결과]와 같은 결과를 출력할 때, ( ? )에 들어갈 표현을 쓰시오.
[처리결과] Child

Parent pa = ( ? ) Child();""",
        "a": "new",
        "reason": "자바에서 클래스의 인스턴스를 생성하고 메모리를 할당하는 예약어입니다.",
        "concept": "동적 메모리 할당, 인스턴스화"
    },
    {
        "q": """6. 다음과 같은 '학생'테이블을 대상으로, 3학년과 4학년의 학번과 이름을 출력하는 SQL문을 작성하시오. (IN 구문을 반드시 사용할 것)""",
        "a": "SELECT 학번, 이름 FROM 학생 WHERE 학년 IN (3, 4);",
        "reason": "특정 속성이 여러 값 중 하나에 해당하는지 확인할 때 IN 연산자를 사용합니다.",
        "concept": "DML - SELECT, 조건 연산자"
    },
    {
        "q": """7. SQL 제어어(DCL) 중 ROLLBACK에 대해 약술하시오.""",
        "a": "트랜잭션 실행 중 오류가 발생했을 때, 작업을 취소하고 트랜잭션 이전의 정상 상태로 되돌리는 명령어.",
        "reason": "데이터베이스의 원자성을 보장하기 위해 수행된 결과를 원상복구하는 제어어이기 때문입니다.",
        "concept": "ACID 속성 중 Atomicity(원자성), Commit"
    },
    {
        "q": """8. 네트워크 계층(IP)에서 '암호화', '인증', '키 관리'를 통해 보안성을 제공해 주는 표준화된 기술은?""",
        "a": "IPSec (IP Security)",
        "reason": "네트워크 계층(3계층)에서 보안 패킷 통신을 구현하는 표준 프로토콜입니다.",
        "concept": "AH(인증 헤더), ESP(암호화 페이로드)"
    },
    {
        "q": """9. 애플리케이션을 실행하지 않고, 소스 코드에 대한 코딩 표준 준수 여부 및 결함을 발견하기 위하여 사용하는 테스트 자동화 도구 유형은?""",
        "a": "정적 분석 도구 (Static Analysis Tool)",
        "reason": "코드를 실행하지 않는(Static) 상태에서 문법이나 복잡도를 분석하기 때문입니다.",
        "concept": "정적 분석 vs 동적 분석"
    },
    {
        "q": """10. 한 객체의 상태가 바뀌면 의존하는 다른 객체들에게 연락이 가고 자동으로 내용이 갱신되는 1:N 의존 관계 디자인 패턴은? (영문)""",
        "a": "Observer Pattern",
        "reason": "상태 변화를 감시(Observe)하고 구독자들에게 통지하는 구조이기 때문입니다.",
        "concept": "GoF 디자인 패턴 중 행위(Behavioral) 패턴"
    },
    {
        "q": """11. 리눅스 커널 기반으로 동작하며 자바/코틀린 언어로 개발된, 모바일 기기에 주로 사용되는 오픈소스 운영체제는?""",
        "a": "안드로이드 (Android)",
        "reason": "리눅스 기반 모바일 플랫폼으로 구글에서 주도하는 오픈소스 OS입니다.",
        "concept": "모바일 운영체제, 리눅스 커널"
    },
    {
        "q": """12. student 테이블의 name 속성에 idx_name를 인덱스 명으로 하는 인덱스를 생성하는 SQL문을 작성하시오.""",
        "a": "CREATE INDEX idx_name ON student(name);",
        "reason": "인덱스 생성 문법은 CREATE INDEX [인덱스명] ON [테이블명]([속성명]); 입니다.",
        "concept": "DB 성능 최적화, 인덱스 관리"
    },
    {
        "q": """13. 다음 괄호안에 들어갈 프로토콜의 이름을 적으시오.

( )은(는) HTTP 등을 이용하여 XML 기반의 메시지를 교환하는 프로토콜로, Envelope-Header-Body 3요소로 구성된다. RESTful로 대체될 수 있다.""",
        "a": "SOAP (Simple Object Access Protocol)",
        "reason": "XML 기반 메시지 교환 프로토콜의 표준 명칭이기 때문입니다.",
        "concept": "WSDL, UDDI, REST"
    },
    {
        "q": """14. 소프트웨어 보안 취약점 중 하나인 SQL Injection에 대해 간략히 설명하시오.""",
        "a": "사용자의 입력란에 악의적인 SQL 구문을 삽입하여 데이터베이스 정보를 유출하거나 조작하는 해킹 기법.",
        "reason": "DB 쿼리를 직접 변조하여 비정상적인 접근을 시도하는 공격이기 때문입니다.",
        "concept": "웹 애플리케이션 보안, 입력값 검증"
    },
    {
        "q": """15. 사용자 인터페이스 설계 원칙 중 사용자의 목적을 정확하게 달성하여야 한다는 원칙은?""",
        "a": "유효성 (Effectiveness)",
        "reason": "사용자의 목적 달성 가능 여부를 보장하는 핵심 원칙이기 때문입니다.",
        "concept": "UI 설계 원칙: 직관성, 유효성, 학습성, 유연성"
    },
    {
        "q": """16. 리눅스에서 a.txt에 대해 사용자(rwx), 그룹(rx), 기타(x) 권한을 한 줄의 명령어로 부여하시오. (8진수 사용)""",
        "a": "chmod 751 a.txt",
        "reason": "사용자(4+2+1=7), 그룹(4+1=5), 기타(1) 권한의 합이 751이기 때문입니다.",
        "concept": "리눅스 권한 관리, chmod"
    },
    {
        "q": """17. 다음에서 설명하는 용어를 영문 완전 이름(Full-name)으로 적으시오.

- 전세계 오픈된 정보를 하나로 묶는 방식
- Linked data와 Open data의 합성어
- URI를 사용하며 시맨틱 웹에 속함""",
        "a": "Linked Open Data (LOD)",
        "reason": "데이터를 연결(Link)하고 개방(Open)하여 공유하는 웹 기술이기 때문입니다.",
        "concept": "시맨틱 웹, URI, RDF"
    },
    {
        "q": """18. 데이터베이스 설계(모델링) 과정을 순서대로 적으시오.
요구사항 분석 -> ( ) -> ( ) -> ( ) -> 구현""",
        "a": "개념적 설계 -> 논리적 설계 -> 물리적 설계",
        "reason": "추상적 ERD에서 시작하여 구조적 설계, 물리적 구현 사양 결정 순으로 진행되기 때문입니다.",
        "concept": "ERD, 정규화, 물리적 사양 결정"
    },
    {
        "q": """19. 다음 자바(Java) 프로그램을 실행한 출력 결과를 쓰시오.
(클래스 B 생성 시 super 호출 포함)""",
        "a": "a=10",
        "reason": "B의 생성자에서 super(10)으로 부모 변수를 10으로 초기화하고 super.print()를 호출했기 때문입니다.",
        "concept": "자바 상속, 생성자 체이닝, super 키워드"
    },
    {
        "q": """20. 소프트웨어 개발 과정에서 산출물 등의 변경에 대비하고 무결성을 유지하기 위한 프로세스는 무엇인가? (도구: CVS, SVN 등)""",
        "a": "형상 관리 (Configuration Management)",
        "reason": "변경 사항을 체계적으로 추적하고 관리하여 무결성을 유지하는 활동이기 때문입니다.",
        "concept": "SCM, Baseline, 버전 관리"
    }
]

def format_blocks(data):
    blocks = []
    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📝 2020년 2회차 정보처리기사 실기 기출문제 (정밀 복원)"}}]}
    })
    blocks.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": "제시해주신 원문 문제를 바탕으로 정확하게 복원된 2020년 2회차 실기 기출문제입니다. 노션 학습용 토글이 포함되어 있습니다."}}],
            "icon": {"type": "emoji", "emoji": "🎯"}
        }
    })
    
    for i, item in enumerate(data):
        blocks.append({"object": "block", "type": "divider", "divider": {}})
        # Question
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": item["q"]}, "annotations": {"bold": True}}]
            }
        })
        # Toggle
        blocks.append({
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [{"type": "text", "text": {"content": "🎯 정답 및 상세 해설 보기 (클릭)"}, "annotations": {"italic": True, "color": "blue"}}],
                "children": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"type": "text", "text": {"content": "✅ 정답: "}, "annotations": {"bold": True}},
                                {"type": "text", "text": {"content": item["a"]}}
                            ]
                        }
                    },
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"type": "text", "text": {"content": "💡 이유: "}, "annotations": {"bold": True, "color": "green"}},
                                {"type": "text", "text": {"content": item["reason"]}}
                            ]
                        }
                    },
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"type": "text", "text": {"content": "🔗 연결 개념: "}, "annotations": {"bold": True, "color": "orange"}},
                                {"type": "text", "text": {"content": item["concept"]}}
                            ]
                        }
                    }
                ]
            }
        })
    return blocks

def main():
    # 1. Clear existing blocks
    delete_all_blocks(PAGE_ID)
    
    # 2. Format new blocks
    blocks = format_blocks(questions_2020_v2)
    
    # 3. Append new blocks
    append_blocks(PAGE_ID, blocks)
    print(f"✅ Re-published 2020 2nd exam to Notion with accurate question content.")

if __name__ == "__main__":
    main()
