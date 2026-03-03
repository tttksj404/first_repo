"""
📍 [BOJ] 2512 예산
> [학습 우선순위: Step 4 - 이진탐색/파라메트릭서치]
> 정해진 총 예산 내에서 각 지방의 예산 요청 중 가능한 한 최대의 상한액을 정하라.

🔍 상세 분석:
- 랜선 자르기와 똑같은 **파라메트릭 서치** 문제입니다.
- "상한액이 X일 때, 전체 예산 M 이내로 지급이 가능한가?"를 물어봅니다.
- 상한액이 커질수록 총 예산액은 늘어납니다.

🏗️ 구현 체크리스트:
1. `start = 0`, `end = max(요청예산)`으로 범위를 잡는다.
2. 상한액을 `mid`로 가정하고 총 지급액을 계산한다.
   - 요청액이 `mid`보다 작으면 그대로 주고, 크면 `mid`만 준다.
3. 총액이 M 이하이면: "상한액을 더 높여보자!" -> `start = mid + 1`, 현재 `mid` 저장.
4. M 초과이면: "너무 많이 줬다. 줄이자." -> `end = mid - 1`.

💡 학생 가이드:
- "왜 end를 max(요청예산)로 잡나요?" 
  -> 예산이 아무리 많아도 지방이 요청한 금액 이상으로 줄 필요는 없기 때문입니다.
"""

import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    requests = list(map(int, input().split()))
    M = int(input()) # 국가 총 예산
    
    # 1. 탐색 범위 (0부터 가장 큰 요청액까지)
    start = 0
    end = max(requests)
    
    ans = 0
    while start <= end:
        # mid를 '상한액'으로 가정!
        mid = (start + end) // 2
        
        # 2. 상한액이 mid일 때의 총 소요 예산 계산
        total_spent = 0
        for r in requests:
            # 요청이 상한액보다 작으면 그대로, 크면 상한액만큼만 지급
            if r <= mid:
                total_spent += r
            else:
                total_spent += mid
                
        # 3. 국가 예산 M 이내로 해결 가능하다면
        if total_spent <= M:
            # 상한액 기록 후, 더 높여보러 떠남
            ans = mid
            start = mid + 1
        # 해결 불가능하면 상한액을 낮춰야 함
        else:
            end = mid - 1
            
    print(ans)

if __name__ == "__main__":
    solve()
