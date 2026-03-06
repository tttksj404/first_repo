"""
📍 [BOJ] 11055 가장 큰 증가하는 부분 수열
> [학습 우선순위: Step 5 - DP/LIS변형]
> 증가하는 부분 수열 중 원소의 합이 가장 큰 것을 구하라.

🔍 상세 분석:
- LIS(11053)와 거의 똑같지만, '개수(+1)' 대신 '원래 숫자 값(+nums[i])'을 더합니다.
- 점화식: `dp[i] = max(dp[j] + nums[i])` (단, j < i 이고 nums[j] < nums[i])

🏗️ 구현 체크리스트:
1. `dp` 배열을 원본 수열 `nums` 복사본으로 초기화한다. (자기 자신만 합쳤을 때의 합)
2. 이중 for문으로 이전 숫자들을 확인한다.
3. `if nums[j] < nums[i]: dp[i] = max(dp[i], dp[j] + nums[i])`

💡 학생 가이드:
- "LIS와 무엇이 다른가요?" 
  -> LIS는 수열의 **'길이'**에 집착하고, 이 문제는 수열의 **'합'**에 집착합니다. 숫자가 작더라도 합이 클 수 있다는 점을 명심하세요!
"""

import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    nums = list(map(int, input().split()))
    
    # dp[i]는 i번째 숫자를 마지막으로 하는 증가 수열의 최대 합
    # 처음엔 자기 자신만 있는 상태이므로 nums 값을 그대로 가져옴
    dp = nums[:]
    
    for i in range(N):
        for j in range(i):
            # 증가하는 관계라면?
            if nums[j] < nums[i]:
                # 이전까지의 최적 합에 현재 숫자를 더한 것과 비교
                dp[i] = max(dp[i], dp[j] + nums[i])
                
    print(max(dp))

if __name__ == "__main__":
    solve()
