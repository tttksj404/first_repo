"""
📍 [BOJ] 11659 구간 합 구하기 4
> [학습 우선순위: Step 4 - 누적 합/기초]
> i번째부터 j번째 수까지 합을 빠르게 구하라.

🔍 상세 분석:
- 구간 합을 매번 구하면 O(N * M)으로 시간 초과가 납니다.
- **누적 합(Prefix Sum)** 기법을 사용하여 미리 '0번부터 i번까지의 합'을 계산해둡니다.
- `i~j` 까지의 합은 `(0~j 까지의 합) - (0~i-1 까지의 합)` 과 같습니다.

🏗️ 구현 체크리스트:
1. 원본 리스트를 입력받는다.
2. 누적 합 배열 `P`를 만든다. (크기 N+1, 첫 칸은 0)
3. `P[i] = P[i-1] + arr[i-1]` 공식으로 채운다.
4. 질의 `i, j`가 들어오면 `P[j] - P[i-1]`을 바로 출력한다.

💡 학생 가이드:
- "P[0]을 왜 0으로 두나요?" 
  -> 1번째부터 j번째까지의 합을 구할 때 `P[j] - P[0]`을 하면 되기 때문에 계산이 아주 깔끔해집니다! (1-indexed 방식)
"""

import sys
input = sys.stdin.readline

def solve():
    N, M = map(int, input().split())
    nums = list(map(int, input().split()))
    
    # 1. 누적 합 배열 만들기 (Prefix Sum)
    # prefix_sum[i]는 1번째부터 i번째 수까지의 총합을 의미함
    prefix_sum = [0] * (N + 1)
    for i in range(N):
        # 이전까지의 누적 합 + 현재 숫자
        prefix_sum[i + 1] = prefix_sum[i] + nums[i]
        
    # 2. 구간 합 질의 처리
    for _ in range(M):
        # i번째부터 j번째까지 (1-indexed 기준)
        i, j = map(int, input().split())
        # 공식: P[j] - P[i-1]
        print(prefix_sum[j] - prefix_sum[i - 1])

if __name__ == "__main__":
    solve()
