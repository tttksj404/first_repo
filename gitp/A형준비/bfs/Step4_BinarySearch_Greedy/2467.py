"""
📍 [BOJ] 2467 용액
> [학습 우선순위: Step 4 - 투 포인터/탐색]
> 이미 정렬된 용액들 중 섞었을 때 특성값이 0에 가장 가까운 두 용액을 찾아라.

🔍 상세 분석:
- 2470번과 거의 똑같지만, 이 문제는 **"이미 정렬된 상태"**로 데이터가 들어옵니다.
- 따라서 `sort()` 과정을 생략해도 되며, 로직은 동일하게 양쪽 끝에서 좁혀오는 투 포인터를 씁니다.

🏗️ 구현 체크리스트:
1. `left = 0`, `right = N-1` 설정.
2. 합이 0보다 작으면 `left++`, 0보다 크면 `right--`.
3. 절댓값이 최소인 순간의 용액 정보를 저장.

💡 학생 가이드:
- "정렬된 상태라면 이진 탐색도 가능하지 않나요?" 
  -> 네, 가능합니다. 하지만 투 포인터가 O(N)으로 훨씬 빠르고 직관적이기 때문에 이 방식을 추천합니다!
"""

import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    # 데이터가 이미 오름차순으로 정렬되어 들어온다는 점이 특징!
    arr = list(map(int, input().split()))
    
    left = 0
    right = N - 1
    
    min_abs = float('inf') # 정답 비교용
    ans = (0, 0) # 결과 용액 쌍
    
    while left < right:
        current_sum = arr[left] + arr[right]
        
        # 지금 섞은 게 0에 더 가깝다면 정답 갱신!
        if abs(current_sum) < min_abs:
            min_abs = abs(current_sum)
            ans = (arr[left], arr[right])
            
        # 합의 상태에 따라 포인터 이동
        if current_sum == 0:
            # 0이면 더 볼 것도 없음!
            break
        elif current_sum < 0:
            # 음수 쪽이 너무 강함 -> 더 큰 양수 값을 가져오기 위해 왼쪽을 오른쪽으로!
            left += 1
        else:
            # 양수 쪽이 너무 강함 -> 더 작은 음수 값을 가져오기 위해 오른쪽을 왼쪽으로!
            right -= 1
            
    print(ans[0], ans[1])

if __name__ == "__main__":
    solve()
