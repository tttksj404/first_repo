"""
📍 [BOJ] 3079 입국심사
> [학습 우선순위: Step 4 - 이진탐색/파라메트릭서치]
> M명이 심사를 받는 데 걸리는 최소 시간을 구하라.

🔍 상세 분석:
- 사람을 배치하는 게 아니라, **'시간'을 탐색**합니다.
- **"T초라는 시간이 주어졌을 때, 모든 심사관이 총 M명 이상을 검사할 수 있는가?"**
- 시간이 많을수록 검사할 수 있는 사람 수도 비례해서 늘어납니다.

🏗️ 구현 체크리스트:
1. `start = 1`, `end = (가장 빠른 심사관 시간 * M)`으로 넉넉히 범위를 잡는다.
2. `mid` 시간 동안 각 심사관이 검사할 수 있는 인원수를 모두 더한다: `mid // 심사시간`.
3. 합계가 M 이상이면: 시간 단축 시도 (`end = mid - 1`, `ans = mid`).
4. M 미만이면: 시간 부족! (`start = mid + 1`).

💡 학생 가이드:
- "왜 end를 (min_time * M)으로 잡나요?" 
  -> 가장 일을 잘하는 사람이 혼자 다 해도 이 시간 안에는 무조건 끝나기 때문입니다. 범위를 너무 크게 잡으면 연산이 늘어날 수 있으니 효율적으로 잡는 게 좋아요.
"""

import sys
input = sys.stdin.readline

def solve():
    # N: 심사대 수, M: 사람 수
    N, M = map(int, input().split())
    times = [int(input()) for _ in range(N)]
    
    # 1. 탐색 범위 (최소 1초부터 최대 예상 시간까지)
    start = 1
    # 가장 빠른 사람이 혼자 M명 다 처리하는 시간으로 상한선 설정
    end = min(times) * M
    
    ans = end
    while start <= end:
        # mid를 '총 걸리는 시간'으로 가정!
        mid = (start + end) // 2
        
        # 2. mid 시간 동안 모든 심사대에서 처리 가능한 총 인원수 계산
        total_people = 0
        for t in times:
            total_people += mid // t
            
        # 3. 목표 인원 M명 이상을 처리할 수 있다면
        if total_people >= M:
            # 성공! 시간을 더 줄여보자
            ans = mid
            end = mid - 1
        # 처리 불가능하면
        else:
            # 시간 더 줘!
            start = mid + 1
            
    print(ans)

if __name__ == "__main__":
    solve()
