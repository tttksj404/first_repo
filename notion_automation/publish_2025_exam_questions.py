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

def format_problem_blocks():
    blocks = []
    
    # Header
    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": "📝 2025년 2회차 정보처리기사 실기 기출문제 모음"}}]}
    })
    
    problems = [
        {
            "id": "문제 1",
            "history": "기출 이력: 2021년 3회 11번, 2025년 2회 1번",
            "content": """다음은 파일 구조와 관련된 설명이다. 설명을 읽고 괄호 안에 들어갈 가장 알맞은 용어를 작성하시오.

데이터베이스의 물리 설계 시, 레코드에 접근하는 방법은 순차 접근 방법, [ ] 방법, 해싱 방법 등이 있다.
이 중 [   ] 방법은 레코드의 키 값과 포인터를 쌍으로 묶어 저장하며, 검색 시 키 값을 기준으로 빠르게 탐색할 수 있도록 설계되어 있다."""
        },
        {
            "id": "문제 2",
            "content": """다음은 데이터베이스 릴레이션의 구성 요소 중 하나에 대한 설명이다. 설명을 읽고 보기에서 알맞은 기호를 골라 작성하시오.

- 릴레이션(Relation)에서 열(Column)을 의미하며 데이터 항목의 속성(Attribute) 또는 특성을 나타낸다.
- 각 열은 고유한 이름을 가지며 특정 도메인(Domain)에서 정의된 값을 갖는다.

[보기]
ㄱ. Cardinality / ㄴ. Domain / ㄷ. Attribute / ㄹ. Degree / ㅂ. Schema / ㅅ. Tuple"""
        },
        {
            "id": "문제 3",
            "content": """다음은 정보보안 관련 문제이다. 아래 내용을 보고 알맞은 단어를 작성하시오.

- 원격 접속과 관련된 보안 프로토콜이며, 암호화된 통신을 제공하는 보안 접속용 프로토콜이다.
- 공개키 기반의 인증 방식을 사용하며, 암호화된 데이터 전송을 지원한다.
- 기본 포트 번호는 22번이다."""
        },
        {
            "id": "문제 4",
            "content": """스케줄링 알고리즘에 관한 다음 설명을 읽고 (1)과 (2)에 알맞은 명칭을 각각 쓰시오.

- (1) CPU burst 시간이 짧은 프로세스를 우선적으로 처리하는 방식 (비선점형 가능)
- (2) 위 방식을 선점형으로 구현한 형태로, 더 짧은 프로세스 도착 시 CPU를 선점함"""
        },
        {
            "id": "문제 5",
            "content": """다음 Java 코드의 출력값을 작성하시오.

```java
public class Main {
    public static void change(String[] data, String s){
        data[0] = s;
        s = "Z";
    }
    public static void main(String[] args) {
        String[] data = { "A" };
        String s = "B";
        change(data, s);
        System.out.print(data[0] + s);
    }
}
```"""
        },
        {
            "id": "문제 6",
            "content": """호스트 IP: 223.13.234.132, 서브넷 마스크: 255.255.255.192 일 때:

1. 네트워크 주소: 223.13.234.( ① )
2. 사용 가능한 호스트 수: ( ② ) 개 (네트워크/브로드캐스트 주소 제외)"""
        },
        {
            "id": "문제 7",
            "content": """다음 디자인 패턴의 명칭을 작성하시오.

- 객체 접근 제어나 기능 부여를 위해 대리 객체를 사용하는 패턴
- 실제 객체 생성을 지연시켜 자원 절약 및 정보은닉 강화 가능"""
        },
        {
            "id": "문제 8",
            "content": """다음 웹 기술의 명칭을 작성하시오.

- ( ) : 웹 페이지 전체를 다시 불러오지 않고 비동기적으로 일부 콘텐츠만 갱신하는 기술
- JavaScript와 XML(또는 JSON)을 이용함"""
        },
        {
            "id": "문제 9",
            "content": """다음 Java 코드의 출력값을 작성하시오.

```java
public class Main {
    static interface F { int apply(int x) throws Exception; }
    public static int run(F f) {
        try { return f.apply(3); }
        catch (Exception e) { return 7; }
    }
    public static void main(String[] args) {
        F f = (x) -> {
            if (x > 2) throw new Exception();
            return x * 2;
        };
        System.out.print(run(f) + run((int n) -> n + 9));
    }
}
```"""
        },
        {
            "id": "문제 10",
            "content": """다음 Java 코드의 출력값을 작성하시오.

```java
public class Main{
    public static class Parent {
        public int x(int i) { return i + 2; }
        public static String id() { return "P"; }
    }
    public static class Child extends Parent {
        public int x(int i) { return i + 3; }
        public String x(String s) { return s + "R"; }
        public static String id() { return "C"; }
    }
    public static void main(String[] args) {
        Parent ref = new Child();
        System.out.println(ref.x(2) + ref.id());
    }
}
```"""
        },
        {
            "id": "문제 11",
            "content": """다음 제어흐름을 참고하여 '분기 커버리지' 테스트 케이스 경로를 작성하시오.

1: P=F -> 2: X>Y? (Y:3, N:4) -> 5: CALL SUB(P) -> 6: RESULT>0? (N:7, Y:종료)"""
        },
        {
            "id": "문제 12",
            "content": """다음 C언어(Queue) 코드의 출력값을 작성하시오.

```c
#include <stdio.h>
#define SIZE 3
// ... (Queue struct & enq/deq)
int main(){
    Queue q = {{0}, 0, 0};
    enq(&q, 1); enq(&q, 2); deq(&q); enq(&q, 3);
    int first = deq(&q); int second = deq(&q);
    printf("%d 그리고 %d", first, second);
    return 0;
}
```"""
        },
        {
            "id": "문제 13",
            "content": """RR 스케줄링(할당량 4ms) 평균 대기시간을 구하시오.
P1(0ms 도착, 8ms 실행), P2(1ms, 4ms), P3(2ms, 9ms), P4(3ms, 5ms)"""
        },
        {
            "id": "문제 14",
            "content": """다음 C언어(Pointer) 코드의 출력값을 작성하시오.

```c
#include <stdio.h>
struct dat { int x, y; };
int main() {
    struct dat a[] = {{1, 2}, {3, 4}, {5, 6}};
    struct dat* ptr = a;
    struct dat** pptr = &ptr;
    (*pptr)[1] = (*pptr)[2];
    printf("%d 그리고 %d", a[1].x, a[1].y);
    return 0;
}
```"""
        },
        {
            "id": "문제 15",
            "content": """다음 Java 코드의 출력값을 작성하시오.

```java
public class Main{
    // ... (BO class with int v)
    public static void main(String[] args) {
        BO a=new BO(1), b=new BO(2), c=new BO(3);
        BO[] arr = {a, b, c};
        BO t = arr[0]; arr[0] = arr[2]; arr[2] = t;
        arr[1].v = arr[0].v;
        System.out.println(a.v + "a" + b.v + "b" + c.v);
    }
}
```"""
        },
        {
            "id": "문제 16",
            "content": """다음 C언어(LinkedList) 코드의 출력값을 작성하시오.

```c
struct node { int p; struct node* n; };
int main() {
    struct node a={1,0}, b={2,0}, c={3,0};
    a.n=&b; b.n=&c; c.n=NULL; c.n=&a; a.n=&b; b.n=NULL;
    struct node* head = &c;
    printf("%d %d %d", head->p, head->n->p, head->n->n->p);
}
```"""
        },
        {
            "id": "문제 17",
            "content": """다음 Python 코드의 출력값을 작성하시오.

```python
lst = [1, 2, 3]
dst = {i: i * 2 for i in lst}
s = set(dst.values())
lst[0] = 99; dst[2] = 7; s.add(99)
print(len(s & set(dst.values())))
```"""
        },
        {
            "id": "문제 18",
            "content": """다음 C언어(Malloc/Stack) 코드의 출력값을 작성하시오.

```c
// ... (func creates linked list in reverse)
int main() {
    struct node* n = func("BEST");
    while (n) { putchar(n->c); n = n->p; }
}
```"""
        },
        {
            "id": "문제 19",
            "content": """TCP 3-way handshake 과정에서 SYN 패킷만 보내고 ACK를 보내지 않아 서버 자원을 고갈시키는 공격 기법은?"""
        },
        {
            "id": "문제 20",
            "content": """employee 테이블에서 π_TTL(employee) 연산 결과를 작성하시오. (중복 제거)
| Index | TTL |
| 1 | 부장 | | 2 | 대리 | | 3 | 과장 | | 4 | 차장 |"""
        }
    ]

    for p in problems:
        blocks.append({"object": "block", "type": "divider", "divider": {}})
        
        # Problem Title
        title_text = p["id"]
        if "history" in p:
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": title_text}}]}
            })
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": p["history"]}, "annotations": {"color": "gray", "italic": True}}]
                }
            })
        else:
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": title_text}}]}
            })

        # Content - Split by lines to handle basic markdown/code
        content = p["content"]
        if "```" in content:
            # Simple handling: find code block
            parts = content.split("```")
            # Text before code
            if parts[0].strip():
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": parts[0].strip()}}]}
                })
            # Code block
            code_lang = parts[1].split("\n")[0].strip()
            code_content = "\n".join(parts[1].split("\n")[1:]).strip()
            blocks.append({
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [{"type": "text", "text": {"content": code_content}}],
                    "language": code_lang if code_lang else "java"
                }
            })
            # Text after code
            if len(parts) > 2 and parts[2].strip():
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": parts[2].strip()}}]}
                })
        else:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]}
            })
            
    return blocks

def main():
    blocks = format_problem_blocks()
    page_id = create_page(PARENT_PAGE_ID, "📝 2025년 2회차 정보처리기사 실기 기출문제 모음", blocks[:50])
    
    if page_id and len(blocks) > 50:
        append_blocks(page_id, blocks[50:])
        print(f"✅ All {len(blocks)} blocks uploaded.")

if __name__ == "__main__":
    main()
