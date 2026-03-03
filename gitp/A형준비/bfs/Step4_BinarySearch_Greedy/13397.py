"""
📍 [BOJ] 13397 구간 나누기 2
> [학습 우선순위: Step 4 - 이진탐색/파라메트릭서치]
> 배열을 M개 이하 구간으로 나눌 때, (구간 최댓값 - 최솟값)의 최대를 최소화하라.

🔍 상세 분석:
- 이진 탐색의 최고 난이도 중 하나입니다.
- **"모든 구간의 점수차가 X 이하가 되도록 M개 이하의 구간으로 나눌 수 있는가?"**
- 그리디하게 앞에서부터 숫자를 포함하다가, (최댓값 - 최솟값)이 X를 넘는 순간 구간을 끊고 새로 시작합니다.

🏗️ 구현 체크리스트:
1. `start = 0`, `end = max(arr) - min(arr)`.
2. `mid`를 허용 가능한 최대 점수차로 가정.
3. 배열을 순회하며 현재 구간의 `min`, `max`를 갱신하고, 차이가 `mid`를 넘으면 `count`를 올리고 `min`, `max` 초기화.
4. 최종 구간 수 `count`가 M 이하면 성공!

💡 학생 가이드:
- "구간 나누기가 왜 그리디인가요?" 
  -> 한 구간을 최대한 길게 가져가야 전체 구간의 개수가 최소가 되기 때문입니다. 그래야 M개 이하로 맞추기가 수월하죠!
"""

import sys
input = sys.stdin.readline

def solve():
    N, M = map(int, input().split())
    nums = list(map(int, input().split()))
    
    # 1. 탐색 범위 (점수차는 0부터 전체 배열의 최대 차이까지)
    start = 0
    end = max(nums)
    
    ans = end
    while start <= end:
        # mid를 '구간의 점수차(최대-최소) 허용 한도'로 가정!
        mid = (start + end) // 2
        
        # 2. 이 한도를 지키면서 몇 개의 구간이 나오는지 계산 (그리디)
        section_cnt = 1 # 첫 번째 구간 시작
        curr_min = nums[0]
        curr_max = nums[0]
        
        for i in range(1, N):
            curr_min = min(curr_min, nums[i])
            curr_max = max(curr_max, nums[i])
            
            # 현재 구간의 차이가 허용 한도(mid)를 넘었다면?
            if curr_max - curr_min > mid:
                # 여기서 구간을 끊고 새로운 구간을 시작한다!
                section_cnt += 1
                curr_min = nums[i]
                curr_max = nums[i]
                
        # 3. 구간 개수가 목표 M개 이하이면 성공!
        if section_cnt <= M:
            # 성공했으니 한도(점수차)를 더 줄여보자
            ans = mid
            end = mid - 1
        else:
            # 구간이 너무 많이 나옴 -> 한도를 넉넉하게 줘야 함
            start = mid + 1
            
    print(ans)

if __name__ == "__main__":
    solve()
