import requests
import os
import json
import time

# Use the token found in .env
NOTION_TOKEN = "REDACTED_NOTION_TOKEN"
PAGE_ID = "325eacc8175a811d8237c7414ef471ea" # 2020년 2회차 페이지 ID

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

def append_blocks(parent_id, blocks):
    url = f"https://api.notion.com/v1/blocks/{parent_id}/children"
    for i in range(0, len(blocks), 50):
        chunk = blocks[i:i+50]
        res = requests.patch(url, headers=HEADERS, json={"children": chunk})
        if res.status_code != 200:
            print(f"❌ Error appending blocks: {res.status_code}, {res.text}")
        time.sleep(0.5)

def create_table_row(cells):
    return {
        "object": "block",
        "type": "table_row",
        "table_row": {
            "cells": [[{"type": "text", "text": {"content": str(cell)}}] for cell in cells]
        }
    }

def main():
    # 1. Clear page
    delete_all_blocks(PAGE_ID)
    
    final_blocks = []
    
    # Title
    final_blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📝 2020년 2회차 정보처리기사 실기 기출문제 (원문 정밀 복원)"}}]}
    })
    
    # Q1
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """1. 다음 보기는 네트워크 인프라 서비스 관리 실무와 관련된 사례이다. 괄호안에 들어갈 가장 적합한 용어를 한글 또는 영문으로 쓰시오.
귀하는 IT회사의 보안관제실에서 근무하고 있다. 정보시스템 운영 중 자연재해나 시스템 장애 등의 이유로 대고객 서비스가 불가능한 경우가 종종 발생한다. 이를 대비하여 백업 및 복구 솔루션을 도입하고자 한다.
백업 및 복구 솔루션은 (            )와 복구 목표 시점(RPO) 기준을 충족할 수 있는 제품으로 선정해야 한다. (           )는 “비상사태 또는 업무중단 시점으로부터 업무가 복구되어 다시 정상가동 될 때까지의 시간” 을 의미하고 복구 목표 시점(RPO)는 "업무 중단 시 각 업무에 필요한 데이터를 여러 백업 수단을 이용하여 복구할 수 있는 기준점"을 의미한다.
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: RTO (Recovery Time Objective)"}}]}}]
        }
    })

    # Q2
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "2. 다음 파이썬(Python) 스크립트의 실행 결과를 적으시오."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [{"type": "text", "text": {"content": """>>> asia={"한국", "중국", "일본"}
>>> asia.add("베트남")
>>> asia.add("중국")
>>> asia.remove("일본")
>>> asia.update(["홍콩", "한국", "태국"])
>>> print(asia)"""}}],
            "language": "python"
        }
    })
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "답을 작성해보세요."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: {'한국', '중국', '베트남', '홍콩', '태국'} (순서 상관없음)"}}]}}]
        }
    })

    # Q3
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """3. 다음에서 설명하는 기술을 영문 약어로 쓰시오.
'비동기식 자바스크립트 XML'을 의미하는 용어로, 클라이언트와 웹서버 간에 XML 데이트를 내부적으로 통신하는 대화식 웹 애플리케이션의 제작을 위해 사용된다. 클라이언트의 요청에 의해 웹서버에서 로딩된 데이터를 웹 브라우저의 페이지에 보여주기 위해 웹 페이지 전체를 '새로고침'할 필요 없이 즉, 현재 페이지에서 필요한 일부만 로딩되도록 하는 웹 개발 기법을 의미한다.
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: AJAX (Asynchronous JavaScript and XML)"}}]}}]
        }
    })

    # Q4
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """4. 다음에서 설명하는 개발방법론은 무엇인지 적으시오.
고객의 요구사항 변화에 유연하게 대응하기 위해 일정한 주기를 반복하면서 개발하며 고객에게 시제품을 지속적으로 제공하며 고객의 요구사항이 정확하게 반영되고 있는지 점검한다. 폭포수 모형에 대비되는 유연한 방법론으로 비교적 소규모 개발 프로젝트에서 각광받고 있는 개발 방법론이다.
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: 애자일 방법론 (Agile Methodology)"}}]}}]
        }
    })

    # Q5
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """5. 다음에 제시된 자바(Java) 프로그램이 [처리 결과]와 같은 결과를 출력할 때, 자바 프로그램의 ( ? )에 들어갈 표현을 대소문자를 구별하여 쓰시오.
[처리결과] 
Child"""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [{"type": "text", "text": {"content": """class Parent {
    void show() {
        System.out.println("Parent");
    }
}
class Child extends Parent {
    void show() {
        System.out.println("Child");
    }
}
public class Exam {
    public static void main(String[] args) {
        Parent pa = (  ?  ) Child();
        pa.show();
    }
}"""}}],
            "language": "java"
        }
    })
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "답을 작성해보세요."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: new"}}]}}]
        }
    })

    # Q6
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """6. 다음과 같은 \"학생\"테이블을 대상으로, 3학년과 4학년의 학번과 이름을 출력하는 SQL문을 작성하시오. (단, in 구문을 반드시 사용할 것)"""}}]}
    })
    
    table_rows = [
        create_table_row(["학번", "이름", "학년"]),
        create_table_row(["1111", "홍길동", "1"]),
        create_table_row(["2222", "임꺽정", "2"]),
        create_table_row(["3333", "유관순", "3"]),
        create_table_row(["4444", "안중근", "3"]),
        create_table_row(["5555", "홍범도", "4"])
    ]
    final_blocks.append({
        "object": "block",
        "type": "table",
        "table": {
            "table_width": 3,
            "has_column_header": True,
            "has_row_header": False,
            "children": table_rows
        }
    })
    
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "답을 작성해보세요."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: SELECT 학번, 이름 FROM 학생 WHERE 학년 IN (3, 4);"}}]}}]
        }
    })

    # Q7
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """7. SQL 제어어(DCL)에는 COMMIT, ROLLBACK, GRANT, REVOKE 가 있다. 그 중 ROLLBACK에 대해 약술하시오.
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: 트랜잭션이 실패하여 작업을 취소하고 이전 상태로 되돌리는 데이터 제어어"}}]}}]
        }
    })

    # Q8
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """8. 네트워크 계층(network layer, 3계층)인 인터넷 프로토콜(IP)에서 '암호화', '인증', '키 관리'를 통해 보안성을 제공해 주는 표준화된 기술
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: IPSec"}}]}}]
        }
    })

    # Q9
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """9. 애플리케이션을 실행하지 않고, 소스 코드에 대한 코딩 표준, 코딩 스타일, 코드 복잡도 및 남은 결함을 발견하기 위하여 사용하는 테스트 자동화 도구 유형은?
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: 정적 분석 (Static Analysis)"}}]}}]
        }
    })

    # Q10
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """10. 다음에서 설명하는 소프트웨어 디자인 패턴을 영문으로 쓰시오.
한 객체의 상태가 바뀌면 그 객체에 의존하는 다른 객체들한테 연락이 가고 자동으로 내용이 갱신되는 방식으로 일 대 다(one-to-many) 의존성을 가지는 디자인 패턴. 
서로 상호작용을 하는 객체 사이에서는 가능하면 느슨하게 결합(Loose coupling)하는 디자인을 사용해야 한다.
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: Observer Pattern"}}]}}]
        }
    })

    # Q11
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """11. 리눅스 커널을 기반으로 동작하며 자바의 코틀린 언어로 개발된, 모바일 기기에 주로 사용되는 오픈소스 플랫폼인 운영체제는 무엇인지 쓰시오.
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: 안드로이드 (Android)"}}]}}]
        }
    })

    # Q12
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """12. 다음 주어진 student 테이블의 name 속성에 idx_name를 인덱스 명으로 하는 인덱스를 생성하는 SQL문을 작성하시오."""}}]}
    })
    table_rows_12 = [
        create_table_row(["id", "name", "grade"]),
        create_table_row(["1111", "홍길동", "1"]),
        create_table_row(["2222", "임꺽정", "2"]),
        create_table_row(["3333", "유관순", "3"]),
        create_table_row(["4444", "안중근", "3"]),
        create_table_row(["5555", "홍범도", "4"])
    ]
    final_blocks.append({
        "object": "block",
        "type": "table",
        "table": {
            "table_width": 3,
            "has_column_header": True,
            "has_row_header": False,
            "children": table_rows_12
        }
    })
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "답을 작성해보세요."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: CREATE INDEX idx_name ON student(name);"}}]}}]
        }
    })

    # Q13
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """13. 다음 괄호안에 들어갈 프로토콜의 이름을 적으시오.
(              )은(는) HTTP 등의 프로토콜을 이용하여 XML 기반의 메시지를 교환하는 프로토콜로, Envelope-Header-Body 주요 3요소로 구성된다. (              )은(는) 유사한 기능을 하는 RESTful로 대체될 수 있다.
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: SOAP"}}]}}]
        }
    })

    # Q14
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """14. 소프트웨어 보안 취약점 중 하나인 SQL Injection에 대해 간략히 설명하시오.
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: 웹페이지의 입력값에 SQL을 삽입하여 오동작을 일으키는 해킹 방식"}}]}}]
        }
    })

    # Q15
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """15. 다음은 사용자 인터페이스 설계 원칙에 대한 설명이다. 괄호안에 들어갈 설계 원칙을 적으시오."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "직관성: 누구나 쉽게 이해하고 사용할 수 있어야 한다."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "(        ): 사용자의 목적을 정확하게 달성하여야 한다."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "학습성: 누구나 쉽게 배우고 익힐 수 있어야 한다."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "유연성: 사용자의 요구사항을 최대한 수용하며, 오류를 최소화하여야 한다."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "답을 작성해보세요."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: 유효성 (Effectiveness)"}}]}}]
        }
    })

    # Q16
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """16. 리눅스 운영체제에서 현재 디렉터리에 위치한 \"a.txt\"에 아래의 조건대로 권한을 부여하고자 한다. 실행해야 하는 명령어를 적으시오."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "사용자에게 읽기,쓰기 실행 권한 부여"}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "그룹에게 읽기, 실행 권한 부여"}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "그 외에게 실행 권한 부여"}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": "한 줄의 명령어로 작성하며, 아라비안 숫자를 사용하여 8진수 권한으로 부여"}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "답을 작성해보세요."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: chmod 751 a.txt"}}]}}]
        }
    })

    # Q17
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """17. 다음에서 설명하는 용어를 영문 완전 이름(Full-name)으로 적으시오.
ㅇ 전세계 오픈된 정보를 하나로 묶는 방식
ㅇ Linked data와 Open data의 합성어
ㅇ URI(Uniform Resource Identifier)를 사용
ㅇ RESTful 방식으로 볼 수 있으며, 링크 기능이 강조된 시멘틱 웹에 속하는 기술
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: Linked Open Data (LOD)"}}]}}]
        }
    })

    # Q18
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """18. 다음은 데이터베이스 설계(모델링) 과정을 간략히 표현한 것이다. 괄호 안에 들어갈 내용을 순서대로 나열하시오.
요구사항 분석 -> (    ) -> (     ) -> (       ) -> 구현
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: 개념적 설계 -> 논리적 설계 -> 물리적 설계"}}]}}]
        }
    })

    # Q19
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "19. 다음 자바(Java) 프로그램을 실행한 출력 결과를 쓰시오."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [{"type": "text", "text": {"content": """class A {
  int a;
  public A(int n) {
      a = n;
  }

  public void print() {
    System.out.println("a=" +  a);
  }
}

class B extends A {
  public B(int n) {
    super(n);
    super.print();
  }
}

public class Exam {
  public static void main(String[] args) {
    B obj = new B(10);
  }
}"""}}],
            "language": "java"
        }
    })
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": "답을 작성해보세요."}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: a=10"}}]}}]
        }
    })

    # Q20
    final_blocks.append({"object": "block", "type": "divider", "divider": {}})
    final_blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": """20. 다음 보기에서 설명하는 것으로 가장 적절한 것은?
소프트웨어 개발 과정에서 산출물 등의 변경에 대비하기 위해 반드시 필요하다. 소프트웨어 리사이클 기간 동안 개발되는 제품의 무결성을 유지하고 소프트웨어의 식별, 편성 및 수정을 통제하는 프로세스를 제공한다. 실수는 최소화하고 생산성의 최대화가 궁극적인 목적이다. 관련 도구로는 CVS, SVN, Clear Case 등이 있다.
답을 작성해보세요."""}}]}
    })
    final_blocks.append({
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": [{"type": "text", "text": {"content": "위키해설 클릭하면 보입니다."}, "annotations": {"italic": True, "color": "blue"}}],
            "children": [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": "정답: 형상 관리 (Configuration Management)"}}]}}]
        }
    })
    
    # 2. Append blocks to page
    append_blocks(PAGE_ID, final_blocks)
    print(f"✅ Successfully re-published 2020 2nd exam with EXACT wording and TABLES.")

if __name__ == "__main__":
    main()
