"""
📍 [BOJ] 1654 랜선 자르기
> [학습 우선순위: Step 4 - 이진탐색/파라메트릭서치]
> 가지고 있는 K개의 랜선을 잘라 N개 이상의 같은 길이 랜선으로 만들 때, 가능한 최대 길이를 구하라.

🔍 상세 분석:
- "최대 길이를 구하라"는 문제를 **"길이 X로 잘랐을 때 N개 이상이 나오는가?"**라는 질문으로 바꿉니다.
- 길이가 길어지면 개수는 줄어듭니다 (단조성). 따라서 **이진 탐색**으로 최적의 X를 찾을 수 있습니다.
- 탐색 범위: 최소 길이 1부터 최대 길이 `max(lans)`까지.

🏗️ 구현 체크리스트:
1. `start = 1`, `end = max(lans)`로 이진 탐색 범위를 잡는다.
2. 중간값 `mid` 길이로 모든 랜선을 잘라본다. (`lan // mid`)
3. 잘려진 개수의 합이 N보다 크거나 같으면? (성공!)
   - "길이를 더 늘려볼까?" -> `start = mid + 1`, 현재 `mid`를 정답 후보로 저장.
4. N보다 작으면? (실패!)
   - "너무 길게 잘랐구나." -> `end = mid - 1`.

💡 학생 가이드:
- "왜 end가 정답이 되나요?" 
  -> 이진 탐색이 끝나면 `end`는 조건을 만족하는 최대 길이에 머물러 있게 됩니다. 파라메트릭 서치의 아주 멋진 특징이죠!
"""

import sys
input = sys.stdin.readline

def solve():
    # K: 이미 가진 개수, N: 필요한 개수
    K, N = map(int, input().split())
    lans = [int(input()) for _ in range(K)]
    
    # 1. 탐색 범위 설정 (최소 1, 최대 가장 긴 랜선 길이)
    start = 1
    end = max(lans)
    
    result = 0 # 정답 저장 변수
    
    while start <= end:
        # mid를 '자르는 길이'라고 가정해보자!
        mid = (start + end) // 2
        
        # 2. mid 길이로 잘랐을 때 나오는 총 개수 카운트
        count = 0
        for x in lans:
            count += x // mid
            
        # 3. 개수가 충분하면(N개 이상)
        if count >= N:
            # 현재 길이 mid는 가능한 답이다! (저장)
            result = mid
            # 더 길게 자를 수 있을지도 모르니 오른쪽 탐색
            start = mid + 1
        # 개수가 모자라면
        else:
            # 너무 길게 잘랐음. 길이를 줄여야 함
            end = mid - 1
            
    print(result)

if __name__ == "__main__":
    solve()
