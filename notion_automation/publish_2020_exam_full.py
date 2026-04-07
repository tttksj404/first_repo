import requests
import os
import json
import time

# Use the token found in .env
NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
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

questions_data_2020 = [
    {
        "q": "1. 정보시스템 운영 중 서버가 다운되거나 자연재해나 시스템 장애 등의 이유로 고객에게 서비스가 불가능한 경우가 종종 발생한다. 이와 같은 상황에서 비상사태 또는 업무중단 시점부터 업무가 복구되어 다시 정상 가동될 때까지의 시간을 의미하는 용어가 무엇인지 쓰시오.",
        "a": "RTO (Recovery Time Objective / 복구 목표 시간)",
        "reason": "업무 중단 시점부터 복구까지 걸리는 '시간' 목표를 의미합니다.",
        "concept": "RPO (Recovery Point Objective): 복구 목표 지점 (데이터 손실 허용량)."
    },
    {
        "q": """2. 다음은 파이썬 코드이다. 출력 결과를 쓰시오.

a={'일본','중국','한국'}
a.add('베트남')
a.add('중국')
a.remove('일본')
a.update(['홍콩','한국','태국'])
print(a)""",
        "a": "{'중국', '태국', '베트남', '한국', '홍콩'} (순서 상관없음)",
        "reason": "Set은 중복을 허용하지 않으며, add/update 시 중복 요소는 무시됩니다.",
        "concept": "파이썬 Set의 특성: 중복 불가, 순서 없음."
    },
    {
        "q": "3. 브라우저가 가지고 있는 XMLHttpRequest 객체를 이용해서 전체 페이지를 새로 고치지 않고도 페이지의 일부분만을 위한 데이터를 로드하는 기법이며, HTML만으로 어려운 다양한 작업을 웹 페이지에서 구현해 이용자가 웹 페이지와 자유롭게 상호작용할 수 있도록 하는 기술명을 쓰시오.",
        "a": "AJAX (Asynchronous JavaScript and XML)",
        "reason": "비동기 방식으로 데이터를 교환하여 페이지 일부만 갱신하는 기술입니다.",
        "concept": "XMLHttpRequest 객체를 사용하는 비동기 통신."
    },
    {
        "q": "4. 절차보다는 사람이 중심이 되어 변화에 유연하고 신속하게 적응하면서 효율적으로 시스템을 개발할 수 있는 신속 적응적 경량 개발방법론으로, 개발 기간이 짧고 신속하며, 워터폴에 대비되는 방법론은 무엇인가?",
        "a": "애자일 (Agile)",
        "reason": "반복적이고 점진적인 개발을 통해 고객의 요구사항에 기민하게 대응하는 방법론입니다.",
        "concept": "XP, Scrum, Kanban 등이 애자일에 포함됩니다."
    },
    {
        "q": """5. 다음은 자바 코드이다. 다음 밑줄에 들어갈 키워드를 쓰시오.

public class good{
	public static void main(String[] args){
    	Parent pa = ____ Child();
        pa.show();
    }
}""",
        "a": "new",
        "reason": "자바에서 객체를 생성하고 메모리를 할당할 때 사용하는 키워드입니다.",
        "concept": "클래스의 인스턴스화."
    },
    {
        "q": "6. 학생 테이블에서 3, 4학년인 학번, 이름을 조회하는 SQL문을 작성하시오. (IN 연산자 사용)",
        "a": "SELECT 학번, 이름 FROM 학생 WHERE 학년 IN (3, 4);",
        "reason": "IN 연산자는 나열된 값 중 하나라도 일치하면 조회합니다.",
        "concept": "다중 값을 비교하는 조건 연산자."
    },
    {
        "q": "7. 트랜잭션 Rollback에 대해 설명하시오.",
        "a": "트랜잭션 실행 중 오류 발생 시, 수행된 작업을 취소하고 이전의 정상 상태로 되돌리는 작업.",
        "reason": "데이터베이스의 원자성(Atomicity)을 보장하기 위한 메커니즘입니다.",
        "concept": "Commit(반영) vs Rollback(취소)."
    },
    {
        "q": "8. 무결성과 인증을 보장하는 인증헤더(AH)와 기밀성을 보장하는 암호화(ESP)를 이용한 프로토콜로 네트워크 계층(IP)에 보안성을 제공해주는 기술은?",
        "a": "IPSec (IP Security)",
        "reason": "네트워크 계층(3계층)에서 IP 패킷 단위로 인증 및 암호화를 수행합니다.",
        "concept": "VPN 등에서 주로 사용되는 보안 프로토콜."
    },
    {
        "q": "9. 애플리케이션을 실행하지 않고 소스 코드 자체를 분석하여 코딩 표준, 스타일, 복잡도 및 결함을 발견하기 위해 사용하는 도구는?",
        "a": "정적 분석 도구 (Static Analysis Tool)",
        "reason": "코드를 실행하지 않는 '정적' 상태에서 결함을 찾기 때문입니다.",
        "concept": "동적 분석(실행 중 분석)과 대비되는 개념."
    },
    {
        "q": "10. 한 객체의 상태가 바뀌면 그 객체에 의존하는 다른 객체들이 연락이 가고 자동으로 내용이 갱신되는 1:N 의존 관계 디자인 패턴은? (영문 Full-Name)",
        "a": "Observer Pattern",
        "reason": "상태 변화를 감시(Observe)하고 알리는 구조이기 때문입니다.",
        "concept": "GoF 디자인 패턴 중 행위(Behavioral) 패턴."
    },
    {
        "q": "11. 리눅스 기반 모바일 운영체제로 자바와 코틀린 언어로 앱을 작성할 수 있고 구글에서 주도하는 오픈 소스 플랫폼은?",
        "a": "안드로이드 (Android)",
        "reason": "리눅스 커널 기반의 개방형 모바일 OS의 대표 주자입니다.",
        "concept": "모바일 운영체제 소프트웨어 스택."
    },
    {
        "q": "12. 학생 테이블의 name 속성에 IDX_NAME 이름으로 인덱스를 생성하는 SQL문을 작성하시오.",
        "a": "CREATE INDEX IDX_NAME ON 학생(NAME);",
        "reason": "CREATE INDEX 문법을 사용하여 검색 성능을 향상시킵니다.",
        "concept": "데이터베이스 성능 최적화 도구."
    },
    {
        "q": "13. HTTP, HTTPS, SMTP를 통해서 XML 기반의 데이터를 주고받는 프로토콜로 웹 서비스 방식에 HTTP 기반의 ( )을/를 사용하여 송수신한다.",
        "a": "SOAP (Simple Object Access Protocol)",
        "reason": "XML 기반의 메시지 교환 프로토콜의 표준 명칭입니다.",
        "concept": "WSDL, UDDI와 함께 웹 서비스의 핵심 요소."
    },
    {
        "q": "14. SQL Injection이 무엇인지 서술하시오.",
        "a": "사용자의 입력란에 악의적인 SQL 구문을 삽입하여 DB 정보를 유출하거나 조작하는 공격 기법.",
        "reason": "DB 쿼리를 직접 변조하여 비정상적인 동작을 유도하기 때문입니다.",
        "concept": "웹 애플리케이션 보안 취약점 공격."
    },
    {
        "q": "15. 사용자에게 읽기/쓰기/실행(7), 그룹에게 읽기/실행(5), 기타에게 실행(1) 권한을 a.txt에 부여하는 명령어를 작성하시오. (8진법)",
        "a": "chmod 751 a.txt",
        "reason": "r(4)+w(2)+x(1)=7, r(4)+x(1)=5, x(1)=1 이므로 751입니다.",
        "concept": "리눅스 파일 접근 권한 설정."
    },
    {
        "q": "16. UI 설계 원칙 중 사용자의 목적을 정확하고 완벽하게 달성할 수 있도록 하는 원칙은?",
        "a": "유효성 (Effectiveness)",
        "reason": "목표 달성 여부가 중심이 되는 원칙이기 때문입니다.",
        "concept": "UI 4대 원칙: 직관성, 유효성, 학습성, 유연성."
    },
    {
        "q": "17. 전 세계 오픈된 정보를 하나로 묶는 방식으로 link data와 open data의 합성어는?",
        "a": "LOD (Linked Open Data)",
        "reason": "개별 데이터를 링크로 연결하여 거대한 데이터망을 구성하는 방식입니다.",
        "concept": "시맨틱 웹 기술의 핵심 구현체."
    },
    {
        "q": "18. 데이터 모델링 절차 3단계를 순서대로 쓰시오.",
        "a": "개념적 모델링 -> 논리적 모델링 -> 물리적 모델링",
        "reason": "추상적 설계에서 실제 구현을 위한 구체적 설계로 나아가는 과정입니다.",
        "concept": "데이터베이스 설계 프로세스."
    },
    {
        "q": """19. 다음 자바 코드의 출력 결과를 쓰시오.

class A{
    private int a;
    public A(int a){ this.a = a; }
    public void display(){ System.out.println("a=" + a); }
}
class B extends A {
    public B(int a){
        super(a);
        super.display();
    }
}
public class good {
    public static void main(String[] args){
        B obj = new B(10);
    }
}""",
        "a": "a=10",
        "reason": "super(a)를 통해 부모 생성자를 호출하여 a를 초기화하고 super.display()를 호출했기 때문입니다.",
        "concept": "자바 상속 및 부모 클래스 참조."
    },
    {
        "q": "20. 소프트웨어 개발 과정에서 발생하는 산출물의 변경 사항을 관리하는 기법은?",
        "a": "형상 관리 (Configuration Management)",
        "reason": "버전 관리 및 산출물의 무결성을 유지하는 종합적인 관리 활동입니다.",
        "concept": "SCM (Software Configuration Management)."
    }
]

def format_blocks(data):
    blocks = []
    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📝 2020년 2회차 정보처리기사 실기 기출문제 모음"}}]}
    })
    blocks.append({
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": "2020년 2회차 실기 기출문제를 해설과 함께 정리했습니다. 각 문항을 풀고 토글을 열어 정답을 확인하세요."}}],
            "icon": {"type": "emoji", "emoji": "📖"}
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
    blocks = format_blocks(questions_data_2020)
    page_id = create_page(PARENT_PAGE_ID, "📝 2020년 2회차 정보처리기사 실기 기출문제 모음", blocks[:50])
    
    if page_id and len(blocks) > 50:
        append_blocks(page_id, blocks[50:])
        print(f"✅ All {len(blocks)} blocks uploaded for 2020 exam.")

if __name__ == "__main__":
    main()
