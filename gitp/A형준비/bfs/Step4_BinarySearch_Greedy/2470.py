"""
📍 [BOJ] 2470 두 용액
> [학습 우선순위: Step 4 - 투 포인터/탐색]
> 산성(양수)과 알칼리성(음수) 용액을 섞어 특성값이 0에 가장 가까운 두 용액을 찾아라.

🔍 상세 분석:
- **"두 수의 합"**을 다루는 문제는 **투 포인터(Two Pointers)**가 가장 강력합니다.
- 배열을 미리 정렬한 뒤, 양쪽 끝(`left`, `right`)에서 포인터를 좁혀옵니다.
- 합이 음수라면 더 큰 값을 더해야 하므로 `left`를 오른쪽으로 옮기고, 양수라면 합을 줄여야 하므로 `right`를 왼쪽으로 옮깁니다.

🏗️ 구현 체크리스트:
1. 용액 리스트를 오름차순으로 정렬한다.
2. `left = 0`, `right = N-1`로 포인터를 설정한다.
3. 두 용액의 합을 확인하며 절댓값이 최소인 경우의 용액 번호를 저장한다.
4. 합이 0보다 작으면 `left += 1`, 크면 `right -= 1`을 수행한다.

💡 학생 가이드:
- "정렬이 왜 필요한가요?" 
  -> 정렬이 되어 있어야 내가 왼쪽 포인터를 옮겼을 때 합이 커질지 작아질지 확실히 예측할 수 있기 때문입니다.
"""

import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    # 1. 정렬 필수! (투 포인터의 전제 조건)
    arr = sorted(list(map(int, input().split())))
    
    left = 0
    right = N - 1
    
    min_abs_sum = float('inf') # 정답을 찾기 위한 비교값 (절댓값)
    ans = [0, 0] # 정답 용액 두 개를 담을 곳
    
    # 2. 양쪽 끝에서부터 포인터를 좁혀오며 검사
    while left < right:
        current_sum = arr[left] + arr[right]
        
        # 지금 섞은 게 지금까지 중 0에 제일 가깝다면 기록!
        if abs(current_sum) < min_abs_sum:
            min_abs_sum = abs(current_sum)
            ans = [arr[left], arr[right]]
            
        # 3. 합의 상태에 따라 포인터 이동
        if current_sum == 0:
            # 0이면 최적해를 찾은 것이므로 즉시 종료
            break
        elif current_sum < 0:
            # 합이 너무 작음 -> 더 큰 양수 값을 가져와야 함 (left 이동)
            left += 1
        else:
            # 합이 너무 큼 -> 더 작은 음수 값을 가져와야 함 (right 이동)
            right -= 1
            
    print(ans[0], ans[1])

if __name__ == "__main__":
    solve()
