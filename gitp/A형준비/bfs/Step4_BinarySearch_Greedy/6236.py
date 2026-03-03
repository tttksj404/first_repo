"""
📍 [BOJ] 6236 용돈 관리
> [학습 우선순위: Step 4 - 이진탐색/파라메트릭서치]
> M번만 돈을 인출하여 N일 동안 생활하려 한다. 한 번 인출할 때의 최소 금액 K를 구하라.

🔍 상세 분석:
- **"한 번에 뽑는 금액 K가 X원일 때, M번 이하의 인출로 N일을 버틸 수 있는가?"**
- K가 클수록 인출 횟수는 줄어듭니다.
- 범위:
  - 최소: `max(daily_costs)` (최소한 하루 지출액만큼은 한 번에 뽑아야 함)
  - 최대: `sum(daily_costs)` (한 번에 다 뽑아버리는 경우)

🏗️ 구현 체크리스트:
1. `start = max(costs)`, `end = sum(costs)` 설정.
2. `mid`를 뽑는 금액으로 가정하고 인출 횟수 계산.
   - 부족할 때마다 다시 `mid`원을 인출하고 횟수 1 증가.
3. 횟수가 M 이하이면 성공! 금액을 줄여본다.
4. M 초과면 실패! 금액을 늘려야 한다.

💡 학생 가이드:
- "남은 돈이 모자라면 남은 돈을 넣고 다시 K원을 인출한다"는 말은, 그냥 부족한 순간에 다시 K원이 채워진다는 뜻으로 이해하면 쉽습니다!
"""

import sys
input = sys.stdin.readline

def solve():
    N, M = map(int, input().split())
    costs = [int(input()) for _ in range(N)]
    
    # 1. 탐색 범위 (최소: 하루치 중 제일 비싼 거, 최대: 몽땅)
    start = max(costs)
    end = sum(costs)
    
    ans = end
    while start <= end:
        # mid를 '한 번 인출할 금액'으로 가정!
        mid = (start + end) // 2
        
        # 2. 이 금액으로 며칠이나 버티고, 몇 번 인출해야 하는지 계산
        count = 1 # 처음 한 번은 무조건 뽑고 시작
        current_money = mid
        
        for c in costs:
            # 수중의 돈으로 오늘 지출이 불가능하다면?
            if current_money < c:
                # 다시 mid원을 뽑는다!
                count += 1
                current_money = mid
            # 돈을 쓴다
            current_money -= c
            
        # 3. 인출 횟수가 목표 M 이내라면
        if count <= M:
            # 성공! 금액을 더 낮출 수 있는지 확인
            ans = mid
            end = mid - 1
        # 인출 횟수가 너무 많으면
        else:
            # 한 번에 더 많이 뽑아야 함
            start = mid + 1
            
    print(ans)

if __name__ == "__main__":
    solve()
