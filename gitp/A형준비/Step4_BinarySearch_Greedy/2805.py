"""
📍 [BOJ] 2805 나무 자르기
> [학습 우선순위: Step 4 - 이진탐색/파라메트릭서치]
> 절단기 높이 H를 설정하여 적어도 M미터의 나무를 가져가기 위한 H의 최댓값을 구하라.

🔍 상세 분석:
- 랜선 자르기의 나무 버전입니다.
- **"높이 H로 나무를 잘랐을 때, 남은 나무 조각들의 합이 M 이상인가?"**
- 높이 H가 높을수록 가져가는 나무 양은 적어집니다.

🏗️ 구현 체크리스트:
1. `start = 0`, `end = max(나무높이)` 설정.
2. `mid` 높이로 잘랐을 때 얻는 나무 양을 구한다: `sum(tree - mid)` (단, tree > mid 인 경우만).
3. 양이 M 이상이면: 성공! 높이를 더 높여보자.
4. 양이 M 미만이면: 실패! 높이를 낮춰야 더 많이 가져간다.

💡 학생 가이드:
- "파이썬에서 sum()을 쓰면 시간 초과가 날 수 있어요!" 
  -> 나무 개수가 100만 개나 되기 때문에, 반복문 내부에서 조건문(`if tree > mid`)과 덧셈을 아주 효율적으로 처리해야 합니다.
"""

import sys
input = sys.stdin.readline

def solve():
    # N: 나무 수, M: 필요한 나무 길이
    N, M = map(int, input().split())
    trees = list(map(int, input().split()))
    
    # 1. 이진 탐색 범위 (높이 0부터 가장 높은 나무까지)
    start = 0
    end = max(trees)
    
    ans = 0
    while start <= end:
        # mid를 '절단기 높이'로 가정!
        mid = (start + end) // 2
        
        # 2. mid 높이로 잘랐을 때 얻을 수 있는 나무 조각의 총합 계산
        log_total = 0
        for tree in trees:
            if tree > mid:
                log_total += (tree - mid)
                
        # 3. 목표치 M 이상을 얻을 수 있다면
        if log_total >= M:
            # 현재 높이는 성공! (기록 후 더 높여봄)
            ans = mid
            start = mid + 1
        # M 미만으로 얻으면
        else:
            # 높이를 너무 높게 설정함. 낮춰야 함
            end = mid - 1
            
    print(ans)

if __name__ == "__main__":
    solve()
