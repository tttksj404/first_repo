"""
📍 [BOJ] 2559 수열
> [학습 우선순위: Step 4 - 슬라이딩 윈도우/기초]
> 연속적인 K일 동안의 온도의 합이 가장 큰 값을 구하라.

🔍 상세 분석:
- 매번 K개의 합을 새로 구하면(O(N*K)), 데이터가 10만 개일 때 너무 느립니다.
- **슬라이딩 윈도우(Sliding Window)** 기법을 사용하면 O(N)으로 해결 가능합니다.
- 창문(윈도우)을 한 칸씩 옆으로 밀면서, **'나가는 값은 빼고 들어오는 값은 더한다'**는 원리입니다.

🏗️ 구현 체크리스트:
1. 처음 0부터 K-1번째까지의 온도의 합을 `current_sum`으로 미리 구한다.
2. `max_sum`을 초기값으로 설정한다.
3. 반복문을 돌며 창문을 한 칸씩 오른쪽으로 민다.
   - `current_sum = current_sum - (방금 나간 왼쪽 값) + (새로 들어온 오른쪽 값)`
4. 매번 `max_sum`과 비교하여 큰 값을 저장한다.

💡 학생 가이드:
- "왜 sum()을 매번 안 쓰나요?" 
  -> sum()은 리스트를 처음부터 끝까지 훑어야 해서 시간이 오래 걸려요. 윈도우 기법은 딱 두 번의 덧셈/뺄셈만으로 다음 합을 알아내기 때문에 훨씬 똑똑한 방법입니다!
"""

import sys
input = sys.stdin.readline

def solve():
    # N: 온도를 측정한 날짜 수, K: 합칠 일수
    N, K = map(int, input().split())
    # 매일의 온도 리스트
    temps = list(map(int, input().split()))
    
    # 1. 처음 K일 동안의 합을 구한다 (초기 윈도우)
    current_sum = sum(temps[:K])
    max_sum = current_sum
    
    # 2. 윈도우를 한 칸씩 오른쪽으로 민다
    # i는 윈도우에서 '빠질' 인덱스를 의미함
    for i in range(N - K):
        # (i)번째 값은 빠지고, (i+K)번째 값이 새로 들어온다
        current_sum = current_sum - temps[i] + temps[i + K]
        
        # 3. 지금까지의 합 중 가장 큰 것 기록
        if current_sum > max_sum:
            max_sum = current_sum
            
    print(max_sum)

if __name__ == "__main__":
    solve()
