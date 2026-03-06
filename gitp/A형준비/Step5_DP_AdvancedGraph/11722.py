"""
📍 [BOJ] 11722 가장 긴 감소하는 부분 수열
> [학습 우선순위: Step 5 - DP/LIS변형]
> 수열에서 가장 긴 감소하는 부분 수열의 길이를 구하라.

🔍 상세 분석:
- LIS의 반대 버전입니다.
- i보다 앞선 j들 중 `nums[j] > nums[i]` 인 경우를 찾으면 됩니다.

🏗️ 구현 체크리스트:
1. `dp` 배열 1로 초기화.
2. 이중 for문 돌며 앞의 숫자가 현재 숫자보다 **더 큰** 경우만 체크.
3. `max(dp)` 출력.

💡 학생 가이드:
- "부등호 방향 하나만 바꾸면 끝!" 
  -> 맞습니다. 하지만 원리는 LIS와 똑같으므로 구조를 완벽히 익히는 게 중요합니다.
"""

import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    nums = list(map(int, input().split()))
    
    dp = [1] * N
    
    for i in range(N):
        for j in range(i):
            # 감소하는 관계(앞에 놈이 더 큼)라면?
            if nums[j] > nums[i]:
                dp[i] = max(dp[i], dp[j] + 1)
                
    print(max(dp))

if __name__ == "__main__":
    solve()
