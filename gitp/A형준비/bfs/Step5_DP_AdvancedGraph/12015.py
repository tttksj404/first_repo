"""
📍 [BOJ] 12015 가장 긴 증가하는 부분 수열 2
> [학습 우선순위: Step 5 - LIS/이진탐색]
> 데이터가 100만 개일 때, 가장 긴 증가하는 부분 수열의 길이를 구하라.

🔍 상세 분석:
- 기존의 O(N^2) 방식은 100만 개 데이터에서 1조 번 연산이 필요해 불가능합니다.
- **이진 탐색을 활용한 O(N log N)** 방식을 사용해야 합니다.
- `lis`라는 리스트를 하나 관리하며, 수열을 하나씩 보면서:
  - 현재 숫자가 `lis`의 마지막 숫자보다 크면? 뒤에 붙인다.
  - 작거나 같으면? `lis` 내부에서 나보다 크거나 같은 첫 번째 숫자를 찾아 내 값으로 바꾼다.

🏗️ 구현 체크리스트:
1. `lis = [nums[0]]` 초기화.
2. `bisect_left` 함수를 임포트하여 위치를 찾는다.
3. 바뀐 `lis` 리스트의 최종 길이가 정답이다.

💡 학생 가이드:
- "왜 내 값을 중간에 끼워 넣나요?" 
  -> 더 작은 값으로 교체해두면, 나중에 더 큰 숫자가 들어올 가능성(여유 공간)을 넓혀주기 때문입니다. 수열의 길이를 유지하며 최적의 구성을 찾아가는 과정이죠!
"""

from bisect import bisect_left
import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    nums = list(map(int, input().split()))
    
    # 1. LIS를 유지할 리스트 생성 (실제 수열과는 다르지만 길이는 정확함)
    lis = [nums[0]]
    
    for i in range(1, N):
        # 현재 숫자가 리스트의 마지막보다 크면? (증가 수열 연장 가능!)
        if nums[i] > lis[-1]:
            lis.append(nums[i])
        else:
            # 작거나 같으면? 리스트 안에서 나보다 크거나 같은 놈을 찾아 내 값으로 교체!
            # bisect_left는 이진 탐색으로 그 위치를 순식간에 찾아줌
            idx = bisect_left(lis, nums[i])
            lis[idx] = nums[i]
            
    # 최종 리스트의 길이가 LIS의 최대 길이
    print(len(lis))

if __name__ == "__main__":
    solve()
