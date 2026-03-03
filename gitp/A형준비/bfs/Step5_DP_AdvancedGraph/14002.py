"""
📍 [BOJ] 14002 가장 긴 증가하는 부분 수열 4
> [학습 우선순위: Step 5 - LIS/역추적]
> LIS의 길이뿐만 아니라 그 수열의 실제 내용까지 출력하라.

🔍 상세 분석:
- LIS를 구한 뒤, 그 **'과정'을 되짚어가는 역추적(Backtracking)** 기술이 필요합니다.
- `dp` 배열을 다 채우고 나서, 최댓값부터 1씩 줄여가며 뒤에서부터 숫자를 골라냅니다.
- 단, 숫자를 고를 때 `A[j] < A[i]` 이면서 `dp[j] == dp[i] - 1` 인 관계를 만족해야 합니다.

🏗️ 구현 체크리스트:
1. O(N^2)로 `dp` 테이블을 완성한다.
2. `max(dp)`를 찾고 그 인덱스부터 역순으로 훑는다.
3. 조건에 맞는 숫자를 바구니에 담고, 마지막에 뒤집어서(`[::-1]`) 출력한다.

💡 학생 가이드:
- "왜 뒤에서부터 찾나요?" 
  -> DP는 앞의 결과가 뒤에 영향을 주기 때문입니다. 마지막에 완성된 최적해부터 거꾸로 찾아가는 것이 훨씬 명확합니다.
"""

import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    A = list(map(int, input().split()))
    
    # 1. DP로 각 위치에서의 LIS 길이 계산
    dp = [1] * N
    for i in range(N):
        for j in range(i):
            if A[j] < A[i]:
                dp[i] = max(dp[i], dp[j] + 1)
                
    # 2. 최장 길이 출력
    max_len = max(dp)
    print(max_len)
    
    # 3. [역추적 시작]
    ans = []
    # 현재 찾고 있는 길이
    target_len = max_len
    # 뒤에서부터 거꾸로 훑음
    for i in range(N - 1, -1, -1):
        if dp[i] == target_len:
            ans.append(A[i])
            target_len -= 1 # 다음으로 1 작은 길이를 가진 숫자를 찾으러 감
            
    # 거꾸로 담았으므로 다시 뒤집어서 정방향으로 출력
    print(*(ans[::-1]))

if __name__ == "__main__":
    solve()
