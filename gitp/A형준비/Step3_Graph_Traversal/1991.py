"""
📍 [BOJ] 1991 트리 순회
> [학습 우선순위: Step 3 - 트리/순회]
> 이진 트리를 전위, 중위, 후위 순회로 탐색한 결과를 출력하라.

🔍 상세 분석:
- 이진 트리의 기본 탐색 기술을 배우는 문제입니다.
- 재귀 함수를 사용하며, '나(루트)'를 언제 출력하느냐에 따라 이름이 바뀝니다.
  1. 전위(Pre): 나 -> 왼쪽 -> 오른쪽
  2. 중위(In): 왼쪽 -> 나 -> 오른쪽
  3. 후위(Post): 왼쪽 -> 오른쪽 -> 나

🏗️ 구현 체크리스트:
1. 딕셔너리에 트리 구조를 저장한다: `tree['A'] = ('B', 'C')`
2. 전위/중위/후위 각각의 재귀 함수를 만든다.
3. 자식이 없는 경우('.')는 재귀를 멈추는 기저 조건으로 처리한다.

💡 학생 가이드:
- "재귀의 순서가 출력을 바꾼다!" 
  -> 코드를 보면 출력(`print`) 문의 위치만 바뀝니다. 재귀 호출은 '그 방향으로 깊숙이 들어간다'는 의미임을 명심하세요.
"""

import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    # 1. 트리 구조를 딕셔너리로 저장
    # 예: {'A': ('B', 'C')} -> A 밑에 왼쪽 B, 오른쪽 C가 있음
    tree = {}
    for _ in range(N):
        root, left, right = input().split()
        tree[root] = (left, right)
        
    # [전위 순회: 나-왼-오]
    def preorder(node):
        if node == '.': return # 자식이 없으면 복귀
        print(node, end='') # 나 먼저 출력
        preorder(tree[node][0]) # 왼쪽 탐색
        preorder(tree[node][1]) # 오른쪽 탐색

    # [중위 순회: 왼-나-오]
    def inorder(node):
        if node == '.': return
        inorder(tree[node][0]) # 왼쪽 끝까지 간 뒤
        print(node, end='') # 나 출력
        inorder(tree[node][1]) # 오른쪽 탐색

    # [후위 순회: 왼-오-나]
    def postorder(node):
        if node == '.': return
        postorder(tree[node][0]) # 왼쪽 가고
        postorder(tree[node][1]) # 오른쪽 가고
        print(node, end='') # 마지막에 나 출력

    # 루트 노드 'A'부터 각각의 순회 시작
    preorder('A')
    print()
    inorder('A')
    print()
    postorder('A')
    print()

if __name__ == "__main__":
    solve()
