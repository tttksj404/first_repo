"""
📍 [BOJ] 1300 K번째 수
> [학습 우선순위: Step 4 - 이진탐색/파라메트릭서치]
> N x N 배열 (A[i][j] = i*j)을 1차원 배열로 옮겨 정렬했을 때 K번째 숫자를 구하라.

🔍 상세 분석:
- N이 10만입니다. N*N은 100억이므로 실제 배열을 만드는 순간 메모리가 터집니다.
- **"숫자 X보다 작거나 같은 수의 개수가 K개 이상인가?"** 라는 질문으로 이진 탐색을 돌립니다.
- X보다 작거나 같은 수의 개수 구하기:
  - i번째 행(i, 2i, 3i, ..., Ni)에서 X보다 작거나 같은 수의 개수는 `X // i` 개입니다. 
  - 단, 한 행에는 최대 N개만 있으므로 `min(N, X // i)` 가 됩니다.

🏗️ 구현 체크리스트:
1. `start = 1`, `end = K`로 범위를 잡는다. (K번째 숫자는 항상 K보다 작거나 같음)
2. `mid`보다 작거나 같은 수의 개수 `cnt`를 각 행별로 합산한다.
3. `cnt >= K` 이면: "더 작은 숫자 중에도 답이 있을까?" -> `end = mid - 1`, 현재 `mid` 저장.
4. `cnt < K` 이면: "숫자를 더 키워야 함." -> `start = mid + 1`.

💡 학생 가이드:
- "왜 end가 K인가요?" 
  -> i*j 행렬에서 K번째 숫자는 K를 넘을 수 없다는 수학적 성질이 있습니다. 범위를 줄여 효율성을 높인 거죠!
"""

import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    K = int(input())
    
    # 1. 탐색 범위 (값의 범위 기준)
    start = 1
    end = K # K번째 숫자는 K보다 클 수 없음
    
    ans = 0
    while start <= end:
        # mid를 'K번째에 있을 후보 숫자'로 가정!
        mid = (start + end) // 2
        
        # 2. mid보다 작거나 같은 숫자가 총 몇 개인지 센다
        count = 0
        for i in range(1, N + 1):
            # i단(i*1, i*2, ..., i*N)에서 mid보다 작거나 같은 것의 개수
            # i*j <= mid  =>  j <= mid // i
            # 하지만 한 행에는 N개까지만 존재함
            count += min(N, mid // i)
            
        # 3. 그 개수가 K개 이상이라면?
        if count >= K:
            # mid는 일단 후보가 됨! 더 작은 값도 확인해봄
            ans = mid
            end = mid - 1
        # 개수가 모자라면
        else:
            # 숫자를 더 키워야 함
            start = mid + 1
            
    print(ans)

if __name__ == "__main__":
    solve()
