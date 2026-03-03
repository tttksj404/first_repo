"""
📍 [BOJ] 12738 가장 긴 증가하는 부분 수열 3
> [학습 우선순위: Step 5 - LIS/이진탐색]
> 수열의 범위가 음수까지 포함될 때, 가장 긴 증가하는 부분 수열의 길이를 구하라.

🔍 상세 분석:
- 12015번과 완전히 동일한 로직입니다.
- 음수가 섞여 있어도 이진 탐색을 이용한 `lis` 리스트 교체 방식은 문제없이 동작합니다.

🏗️ 구현 체크리스트:
1. `bisect_left` 모듈 활용.
2. `lis` 리스트 구성 로직 동일.

💡 학생 가이드:
- "숫자의 크기와 상관없다!" 
  -> 이진 탐색 방식은 숫자의 값이 얼마나 크든, 음수든 상관없이 오직 '대소 관계'만 봅니다. 그래서 매우 강력한 툴입니다.
"""

from bisect import bisect_left
import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    nums = list(map(int, input().split()))
    
    # 음수가 섞여 있어도 상관없음
    lis = [nums[0]]
    
    for i in range(1, N):
        if nums[i] > lis[-1]:
            lis.append(nums[i])
        else:
            idx = bisect_left(lis, nums[i])
            lis[idx] = nums[i]
            
    print(len(lis))

if __name__ == "__main__":
    solve()
