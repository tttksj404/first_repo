"""
📍 [BOJ] 5639 이진 검색 트리
> [학습 우선순위: Step 3 - 트리/재귀분할]
> 전위 순회 결과만 보고 후위 순회 결과를 출력하라.

🔍 상세 분석:
- 이진 검색 트리(BST)의 핵심 성질을 이용합니다.
- **"왼쪽 자식 < 나(루트) < 오른쪽 자식"**
- 전위 순회는 [루트, (나머지)] 형태입니다. 나머지 부분에서 루트보다 처음으로 커지는 지점이 바로 '오른쪽 서브트리'의 시작점입니다.
- 이 경계를 기준으로 영역을 쪼개며 재귀적으로 후위 순회(왼-오-나)를 출력하면 됩니다.

🏗️ 구현 체크리스트:
1. 입력 개수가 안 주어지므로 `sys.stdin.read().split()`으로 통째로 받는다.
2. `post_order(start, end)` 함수:
   - 현재 범위의 첫 번째 숫자가 `root`.
   - `root`보다 큰 숫자가 나오는 위치를 `mid`로 찾는다.
   - `(start+1, mid-1)` 은 왼쪽, `(mid, end)` 는 오른쪽!
   - 왼쪽 호출 -> 오른쪽 호출 -> 루트 출력 순서로 진행.

💡 학생 가이드:
- "왜 트리를 직접 안 만드나요?" 
  -> 노드 클래스를 만들고 삽입해도 되지만, 배열의 인덱스 범위를 쪼개는 방식(분할 정복)이 훨씬 빠르고 메모리 효율적입니다.
"""

import sys
# 트리 깊이가 깊을 수 있으므로 재귀 한도 확장
sys.setrecursionlimit(20000)
input = sys.stdin.read

def solve():
    # 전위 순회 결과 리스트 (입력 끝까지 받기)
    nums = list(map(int, input().split()))
    
    def post_order(start, end):
        # 기저 조건: 볼 영역이 없으면 종료
        if start > end:
            return
            
        # 1. 현재 영역의 첫 번째는 무조건 루트!
        root = nums[start]
        
        # 2. 루트보다 큰 값이 처음 나오는 곳을 찾는다 (오른쪽 트리 시작점)
        # 만약 모든 값이 루트보다 작다면 mid는 end + 1이 됨
        mid = start + 1
        while mid <= end:
            if nums[mid] > root:
                break
            mid += 1
            
        # 3. [후위 순회] 순서대로 재귀 호출
        # 왼쪽 서브트리 (루트 다음부터 mid 직전까지)
        post_order(start + 1, mid - 1)
        # 오른쪽 서브트리 (mid부터 끝까지)
        post_order(mid, end)
        # 마지막으로 나(루트)를 출력
        print(root)

    # 전체 리스트에 대해 함수 호출
    post_order(0, len(nums) - 1)

if __name__ == "__main__":
    solve()
