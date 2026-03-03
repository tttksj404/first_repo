"""
📍 [BOJ] 2110 공유기 설치
> [학습 우선순위: Step 4 - 이진탐색/파라메트릭서치]
> 가장 인접한 두 공유기 사이의 거리를 최대화하라.

🔍 상세 분석:
- "최소 거리를 최대화" -> 파라메트릭 서치의 단골 멘트입니다.
- **"공유기 사이의 간격을 적어도 D 이상으로 했을 때, 공유기 C개를 다 설치할 수 있는가?"**
- 간격 D가 좁을수록 더 많은 공유기를 설치할 수 있습니다.

🏗️ 구현 체크리스트:
1. 집 위치 리스트를 오름차순 정렬한다. (필수!)
2. `start = 1` (최소 거리), `end = (맨 끝 집 - 맨 첫 집)` (최대 거리).
3. `mid` 간격으로 공유기를 설치해본다. (그리디하게 첫 집부터 간격 넘을 때마다 설치)
4. 설치 개수가 C 이상이면: "간격을 더 넓혀보자!" -> `start = mid + 1`, 현재 `mid` 저장.
5. C 미만이면: "간격이 너무 넓어서 설치를 다 못 함." -> `end = mid - 1`.

💡 학생 가이드:
- "설치를 어떻게 하나요?" 
  -> 첫 번째 집에는 무조건 설치하는 게 이득입니다. 그 후 현재 위치에서 `mid` 이상 떨어진 가장 가까운 집을 찾아 다음 공유기를 설치해 나가는 방식(Greedy)을 씁니다.
"""

import sys
input = sys.stdin.readline

def solve():
    # N: 집 개수, C: 설치할 공유기 수
    N, C = map(int, input().split())
    # 1. 집 좌표 정렬 (이진 탐색을 위한 준비)
    houses = sorted([int(input()) for _ in range(N)])
    
    # 2. 탐색 범위 (거리 기준)
    start = 1 # 최소 인접 거리
    end = houses[-1] - houses[0] # 최대 인접 거리
    
    ans = 0
    while start <= end:
        # mid를 '인접한 두 공유기 사이의 최소 거리'로 가정!
        mid = (start + end) // 2
        
        # 3. mid 거리 이상을 띄우면서 공유기를 몇 개 설치할 수 있는지 확인 (그리디)
        count = 1 # 첫 번째 집은 무조건 설치
        last_installed = houses[0]
        
        for i in range(1, N):
            # 마지막으로 설치한 집과 현재 집의 거리가 mid 이상이면 설치!
            if houses[i] - last_installed >= mid:
                count += 1
                last_installed = houses[i]
                
        # 4. 설치된 개수가 목표 C개 이상이면
        if count >= C:
            # 성공! 이 거리는 가능하다. 더 늘려보자.
            ans = mid
            start = mid + 1
        # C개보다 적게 설치되면
        else:
            # 간격이 너무 넓음. 줄여야 함
            end = mid - 1
            
    print(ans)

if __name__ == "__main__":
    solve()
