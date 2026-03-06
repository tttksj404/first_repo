"""
📍 [BOJ] 14888 연산자 끼워넣기
> [학습 우선순위: Step 2 - 백트래킹/수식]
> N개의 숫자 사이에 더하기, 빼기, 곱하기, 나누기를 넣어 만들 수 있는 최대/최소값을 구하라.

🔍 상세 분석:
- 숫자의 순서는 정해져 있고, 연산자만 어떤 순서로 쓸지 정하면 됩니다.
- 연산자들의 개수가 각각 정해져 있으므로, 남은 연산자 개수를 하나씩 줄여가며 DFS를 돌립니다.
- 삼성 A형에서 정말 좋아하는 전형적인 백트래킹 유형입니다.

🏗️ 구현 체크리스트:
1. DFS 함수 인자: (현재까지 사용한 숫자 개수, 현재까지의 계산 결과, 남은 +, -, *, / 개수).
2. 기저 조건: 숫자를 N개 다 썼을 때, 최댓값과 최솟값을 갱신한다.
3. 유도 파트: 연산자가 1개라도 남아있다면, 그 연산자를 쓰고 개수를 하나 줄여 재귀 호출한다.
4. 음수 나눗셈 주의: `int(a / b)`를 사용하면 파이썬에서도 C++ 스타일의 정수 나눗셈이 가능합니다.

💡 학생 가이드:
- "나눗셈 계산법이 왜 다른가요?" 
  -> 파이썬의 `//`는 내림 연산(Floor)입니다. `-5 // 2 = -3`이 되죠. 하지만 문제 조건(C++14 기준)은 0을 향해 자르므로 `-5 / 2 = -2.5`에서 정수 부분인 `-2`를 취해야 합니다. 그래서 `int(a / b)`가 정답입니다!
"""

import sys
input = sys.stdin.readline

# N: 숫자의 개수
N = int(input())
# nums: 숫자 리스트
nums = list(map(int, input().split()))
# 연산자 개수 (더하기, 빼기, 곱하기, 나누기 순)
add, sub, mul, div = map(int, input().split())

# 최댓값과 최솟값 초기화 (최대 10억, 최소 -10억 범위)
max_val = -float('inf')
min_val = float('inf')

def dfs(idx, current_res, a, s, m, d):
    """
    idx: 이번에 연산할 숫자의 위치
    current_res: 지금까지 계산된 결과값
    a, s, m, d: 각각 남은 더하기, 빼기, 곱하기, 나누기 개수
    """
    global max_val, min_val
    
    # [기저 조건] 모든 숫자를 다 계산했을 때
    if idx == N:
        max_val = max(max_val, current_res)
        min_val = min(min_val, current_res)
        return

    # [유도 파트] 연산자가 남아있다면 사용하고 다음 숫자로 넘어간다
    if a > 0: # 더하기가 남았으면
        dfs(idx + 1, current_res + nums[idx], a - 1, s, m, d)
    if s > 0: # 빼기가 남았으면
        dfs(idx + 1, current_res - nums[idx], a, s - 1, m, d)
    if m > 0: # 곱하기가 남았으면
        dfs(idx + 1, current_res * nums[idx], a, s, m - 1, d)
    if d > 0: # 나누기가 남았으면
        # 파이썬 정수 나눗셈 주의: int(a / b) 사용
        dfs(idx + 1, int(current_res / nums[idx]), a, s, m, d - 1)

# 첫 번째 숫자를 시작 결과값으로 넣고, 1번 인덱스 숫자부터 연산 시작
dfs(1, nums[0], add, sub, mul, div)

print(max_val)
print(min_val)
