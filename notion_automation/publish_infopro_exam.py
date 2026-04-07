import requests
import os
import json
import time

# Use the token found in .env
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
PARENT_PAGE_ID = "31feacc8-175a-81ca-9422-e98484530d97" # 정보처리기사 실기 기출 해설

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def create_page(parent_id, title, blocks):
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"page_id": parent_id},
        "properties": {
            "title": {"title": [{"text": {"content": title}}]}
        },
        "children": blocks
    }
    res = requests.post(url, headers=HEADERS, json=payload)
    if res.status_code == 200:
        print(f"✅ Page created successfully: {res.json().get('url')}")
        return res.json().get('id')
    else:
        print(f"❌ Error: {res.status_code}, {res.text}")
        return None

def append_blocks(block_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{block_id}/children"
    for i in range(0, len(blocks), 50):
        chunk = blocks[i:i+50]
        res = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if res.status_code != 200:
            print(f"❌ Error appending blocks: {res.status_code}, {res.text}")
        time.sleep(0.5)

questions_data = [
    {
        "q": "1. 정보시스템 운영 중 서버가 다운되거나 자연재해나 시스템 장애 등의 이유로 고객에게 서비스가 불가능한 경우가 종종 발생한다. 이와 같은 상황에서 비상사태 또는 업무중단 시점부터 업무가 복구되어 다시 정상 가동될 때까지의 시간을 의미하는 용어가 무엇인지 쓰시오.",
        "a": "RTO (Recovery Time Objective / 복구 목표 시간)",
        "reason": "비상사태 또는 업무 중단 시점부터 업무가 복구되어 다시 정상 가동될 때까지의 시간적 목표를 의미합니다.",
        "concept": "RPO (Recovery Point Objective): 복구 목표 지점 (데이터 손실 허용 시점), MTTR (Mean Time To Repair): 평균 수리 시간."
    },
    {
        "q": """2. 다음은 파이썬 코드이다. 출력 결과를 쓰시오.

a={'일본','중국','한국'}
a.add('베트남')
a.add('중국')
a.remove('일본')
a.update(['홍콩','한국','태국'])
print(a)""",
        "a": "{'중국', '태국', '베트남', '한국', '홍콩'} (순서 무관)",
        "reason": "집합(set)은 중복을 허용하지 않으며, add()와 update() 시 중복된 요소는 무시됩니다. remove()는 요소를 삭제합니다.",
        "concept": "파이썬의 set은 순서가 없고 중복을 허용하지 않는 자료구조입니다."
    },
    {
        "q": "3. 브라우저가 가지고 있는 XMLHttpRequest 객체를 이용해서 전체 페이지를 새로 고치지 않고도 페이지의 일부분만을 위한 데이터를 로드하는 기법이며, HTML만으로 어려운 다양한 작업을 웹 페이지에서 구현해 이용자가 웹 페이지와 자유롭게 상호작용할 수 있도록 하는 기술명을 쓰시오.",
        "a": "AJAX (Asynchronous JavaScript and XML)",
        "reason": "전체 페이지를 새로고침하지 않고 브라우저의 XMLHttpRequest 객체를 이용해 일부 데이터만 로드하는 비동기 통신 기술입니다.",
        "concept": "JSON (JavaScript Object Notation): 최근 AJAX에서 데이터 교환 형식으로 XML 대신 주로 사용됩니다."
    },
    {
        "q": "4. 절차보다는 사람이 중심이 되어 변화에 유연하고 신속하게 적응하면서 효율적으로 시스템을 개발할 수 있는 신속 적응적 경량 개발방법론으로, 개발 기간이 짧고 신속하며, 워터폴에 대비되는 방법론으로 최근 회사에서 각광받는 방법론은 무엇인가?",
        "a": "애자일 (Agile)",
        "reason": "사람 중심, 변화에 유연, 짧은 개발 주기(Iterative) 등을 특징으로 하는 경량 개발방법론입니다.",
        "concept": "XP (Extreme Programming), Scrum, Kanban, Lean 등이 애자일 방법론의 예시입니다."
    },
    {
        "q": """5. 다음은 자바 코드이다. 다음 밑줄에 들어갈 키워드를 쓰시오.

Parent pa = ____ Child();""",
        "a": "new",
        "reason": "자바에서 클래스의 인스턴스(객체)를 동적으로 메모리에 할당(생성)할 때 사용하는 키워드입니다.",
        "concept": "업캐스팅(Upcasting): 자식 클래스 객체를 부모 클래스 타입의 변수에 할당하는 것."
    },
    {
        "q": "6. 학생 테이블에서 3, 4학년인 학번, 이름을 조회하는 SQL문을 작성하시오. (IN 연산자 사용)",
        "a": "SELECT 학번, 이름 FROM 학생 WHERE 학년 IN (3, 4);",
        "reason": "특정 속성값이 리스트 내에 포함된 데이터를 조회할 때 IN 연산자를 사용합니다.",
        "concept": "OR 연산자로도 표현 가능합니다. (학년 = 3 OR 학년 = 4)"
    },
    {
        "q": "7. 트랜잭션 Rollback에 대해 설명하시오.",
        "a": "트랜잭션 실행 중 오류가 발생했을 때, 지금까지 수행한 작업을 취소하고 이전의 정상 상태(Commit 지점)로 되돌리는 작업.",
        "reason": "데이터베이스의 원자성(Atomicity)을 보장하기 위해 실패한 트랜잭션을 원상복구하는 메커니즘입니다.",
        "concept": "Commit: 작업을 최종 승인하고 반영하는 것. ACID: 트랜잭션의 4대 속성."
    },
    {
        "q": "8. 무결성과 인증을 보장하는 인증헤더(AH)와 기밀성을 보장하는 암호화(ESP)를 이용한 프로토콜로 네트워크 계층(IP)에 보안성을 제공해주는 표준화된 기술을 쓰시오.",
        "a": "IPSec (IP Security)",
        "reason": "IP 계층(3계층)에서 무결성/인증(AH)과 기밀성(ESP)을 제공하는 보안 프로토콜입니다.",
        "concept": "AH: 인증 및 무결성 보장. ESP: 암호화 및 기밀성 보장."
    },
    {
        "q": "9. 애플리케이션을 실행하지 않고, 소스 코드에 대한 코딩 표준, 스타일, 복잡도 및 결함을 발견하기 위해 사용하는 도구는 무엇인지 쓰시오.",
        "a": "정적 분석 도구 (Static Analysis Tool)",
        "reason": "프로그램을 실행하지 않고 코드 자체를 분석하여 논리적 결함이나 보안 취약점을 찾아내기 때문입니다.",
        "concept": "동적 분석: 실제 프로그램을 실행하며 결함을 찾는 방식."
    },
    {
        "q": "10. 한 객체의 상태가 바뀌면 그 객체에 의존하는 다른 객체들이 연락이 가고 자동으로 내용이 갱신되는 방법으로 일대 다의 의존성을 가지며 상호작용하는 객체 사이에서는 가능하면 느슨하게 결합하는 디자인 패턴을 쓰시오. (영문 Full-Name)",
        "a": "Observer Pattern",
        "reason": "상태 변화를 감시하고 변화 시 의존된 객체들에게 자동으로 통지하는 디자인 패턴입니다.",
        "concept": "발행-구독(Publish-Subscribe) 모델과 유사하며 느슨한 결합을 구현합니다."
    },
    {
        "q": "11. 리눅스 기반 모바일 운영체제로 자바와 코틀린 언어로 응용 프로그램을 작성할 수 있게 했고, 컴파일 된 바이트 코드를 구동할 수 있는 런타임 라이브러리를 제공하는 운영체제는 무엇인지 쓰시오.",
        "a": "안드로이드 (Android)",
        "reason": "구글 주도의 리눅스 커널 기반 모바일 OS로, 자바/코틀린 기반 앱 개발 환경을 제공합니다.",
        "concept": "ART (Android Runtime): 안드로이드의 최신 런타임 환경."
    },
    {
        "q": "12. 학생 테이블의 name 속성에 IDX_NAME 이름으로 인덱스를 생성하는 SQL문을 작성하시오.",
        "a": "CREATE INDEX IDX_NAME ON 학생(NAME);",
        "reason": "인덱스 생성 기본 문법은 CREATE INDEX 인덱스명 ON 테이블명(속성명)입니다.",
        "concept": "인덱스는 검색 속도를 향상시키지만 추가적인 저장 공간과 관리 비용이 발생합니다."
    },
    {
        "q": "13. HTTP, HTTPS, SMTP를 통해서 XML 기반의 데이터를 주고받는 프로토콜로 웹 서비스 방식에 HTTP 기반의 ( )을/를 사용하여 송수신한다. ( ) 대신 레스트풀(RESTful) 프로토콜로 대체할 수 있다.",
        "a": "SOAP (Simple Object Access Protocol)",
        "reason": "XML 기반 메시지 교환 프로토콜로, 강력한 표준과 보안 기능을 제공하지만 REST에 비해 무겁습니다.",
        "concept": "WSDL: 웹 서비스 기술 언어, UDDI: 서비스 등록 및 발견."
    },
    {
        "q": "14. SQL Injection이 무엇인지 서술하시오.",
        "a": "사용자의 입력란에 악의적인 SQL 구문을 삽입하여 데이터베이스 정보를 유출하거나 조작하는 공격 기법.",
        "reason": "애플리케이션이 사용자 입력을 제대로 필터링하지 않을 때 발생하는 보안 취약점입니다.",
        "concept": "Prepared Statement를 사용하거나 입력값 검증을 통해 방어할 수 있습니다."
    },
    {
        "q": "15. 사용자에게 읽기/쓰기/실행(7), 그룹에게 읽기/실행(5), 기타에게 실행(1) 권한을 a.txt에 부여하는 명령어를 작성하시오. (8진법 사용)",
        "a": "chmod 751 a.txt",
        "reason": "r(4), w(2), x(1) 값을 더해 권한을 표현합니다. 4+2+1=7, 4+1=5, 1=1.",
        "concept": "chmod: 파일이나 디렉토리의 접근 권한을 변경하는 명령어."
    },
    {
        "q": "16. UI 설계 원칙에서 정확하고 완벽하게 사용자의 목표가 달성될 수 있도록 제작할 수 있어야 한다. 다음 빈칸에 들어갈 특징은 무엇인가? (직관성, 학습성, 유연성, ...)",
        "a": "유효성 (Effectiveness)",
        "reason": "사용자의 목적을 정확하고 완전하게 달성할 수 있도록 보장하는 원칙입니다.",
        "concept": "UI 4대 원칙: 직관성, 유효성, 학습성, 유연성."
    },
    {
        "q": "17. 전 세계 오픈된 정보를 하나로 묶는 방식으로 link data와 open data의 합성어가 무엇인지 쓰시오.",
        "a": "LOD (Linked Open Data)",
        "reason": "웹상의 데이터를 개별적으로 두지 않고 연결하여 거대한 데이터베이스처럼 활용하는 방식입니다.",
        "concept": "시맨틱 웹(Semantic Web): 컴퓨터가 데이터의 의미를 이해하고 처리하는 지능형 웹."
    },
    {
        "q": "18. 데이터 모델링 절차이다. 빈칸을 채우시오. (요구사항 분석 -> (1) -> (2) -> (3))",
        "a": "1. 개념적 모델링, 2. 논리적 모델링, 3. 물리적 모델링",
        "reason": "추상적 개념에서 시작하여 구조적 설계(정규화), 최종적으로 하드웨어 사양에 맞춘 구현 순서입니다.",
        "concept": "ERD(Entity-Relationship Diagram): 개념적 모델링의 대표적 결과물."
    },
    {
        "q": """19. 다음 자바 코드의 출력 결과를 쓰시오. (클래스 A, B 상속 관계 및 super.display() 호출)""",
        "a": "a=10",
        "reason": "자식 클래스 B 생성자에서 super(a)로 부모의 변수를 초기화하고 super.display()로 부모의 메서드를 실행했기 때문입니다.",
        "concept": "super 키워드: 부모 클래스의 멤버(변수, 메서드)에 접근하거나 부모 생성자를 호출할 때 사용."
    },
    {
        "q": "20. 소프트웨어 개발 과정에서 변경 사항을 관리하는 기법은 ( ) 기법이라고 하며, 도구로는 CVS, SVN, Git 등이 있다. 빈칸에 알맞은 용어를 쓰시오.",
        "a": "형상 관리 (Configuration Management)",
        "reason": "개발 중 발생하는 모든 산출물의 버전과 변경 사항을 체계적으로 관리하는 활동입니다.",
        "concept": "SCM (Software Configuration Management), Baseline(기준선)."
    }
]

def format_blocks(data):
    blocks = []
    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📝 정보처리기사 실기 20문항 복원 및 해설"}}, {"type": "text", "text": {"content": " (2026-03-16)"}, "annotations": {"color": "gray"}}]}
    })
    blocks.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": "이 자료는 정보처리기사 실기 시험의 주요 개념을 정리하고, 각 문항별 정답, 이유, 연결 개념을 포함하고 있습니다."}}],
            "icon": {"type": "emoji", "emoji": "💡"}
        }
    })
    
    for item in data:
        blocks.append({"object": "block", "type": "divider", "divider": {}})
        # Question
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": item["q"]}, "annotations": {"bold": True}}]
            }
        })
        # Toggle for Answer/Reason/Concept
        blocks.append({
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [{"type": "text", "text": {"content": "🎯 정답 및 해설 보기 (클릭)"}, "annotations": {"italic": True, "color": "blue"}}],
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
    blocks = format_blocks(questions_data)
    # Create page with initial blocks (first 50)
    page_id = create_page(PARENT_PAGE_ID, "📝 정보처리기사 실기 복원 및 예상 문제 해설 (2026-03-16)", blocks[:50])
    
    if page_id and len(blocks) > 50:
        # Append remaining blocks
        append_blocks(page_id, blocks[50:])
        print(f"✅ Remaining {len(blocks)-50} blocks appended.")

if __name__ == "__main__":
    main()
