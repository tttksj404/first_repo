"""
📍 [BOJ] 2579 계단 오르기
> [학습 우선순위: Step 5 - DP/제약조건]
> 계단을 오르며 얻는 최대 점수를 구하라. (연속 세 계단 금지!)

🔍 상세 분석:
- **"연속 3칸 금지"**라는 무서운 조건이 있습니다.
- i번째 계단에 도착하는 시나리오는 두 가지뿐입니다:
  1. (i-2)번째 계단을 밟고 2칸 점프해서 오는 경우 (이전 단계는 뭐였든 상관없음!)
  2. (i-3) -> (i-1) -> i 순서로 오는 경우 (이래야 i-2를 건너뛰어서 연속 3칸이 안 됨!)

🏗️ 구현 체크리스트:
1. `dp[i]` 를 i번째 계단까지의 최대 점수로 정의한다.
2. 초기값 `dp[1]`, `dp[2]`, `dp[3]`을 신중하게 채운다.
3. 점화식: `dp[i] = max(dp[i-2], dp[i-3] + score[i-1]) + score[i]`

💡 학생 가이드:
- "N=1, 2일 때를 왜 따로 처리하나요?" 
  -> `dp[3]`을 계산하려고 하면 인덱스 에러가 날 수 있기 때문입니다. 항상 데이터가 아주 작을 때를 대비하는 습관을 들여야 합니다.
"""

import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    # 0번 인덱스는 비워두고 1번부터 사용 (편의성)
    scores = [0] * (N + 1)
    for i in range(1, N + 1):
        scores[i] = int(input())
        
    # 계단이 1개나 2개인 경우 예외 처리
    if N == 1:
        print(scores[1]); return
    if N == 2:
        print(scores[1] + scores[2]); return
        
    # dp[i]는 i번째 계단에 도달했을 때의 최대 점수
    dp = [0] * (N + 1)
    
    # 1. 초기값 설정
    dp[1] = scores[1]
    dp[2] = scores[1] + scores[2]
    # 3번째 계단: (1, 3) 밟기 vs (2, 3) 밟기
    dp[3] = max(scores[1] + scores[3], scores[2] + scores[3])
    
    # 2. 4번째 계단부터 점화식 적용
    for i in range(4, N + 1):
        # [방법 A] i-2에서 2칸 점프해서 온다 -> dp[i-2] + score[i]
        # [방법 B] i-3 -> i-1 -> i 순으로 온다 -> dp[i-3] + score[i-1] + score[i]
        dp[i] = max(dp[i - 2], dp[i - 3] + scores[i - 1]) + scores[i]
        
    print(dp[N])

if __name__ == "__main__":
    solve()
