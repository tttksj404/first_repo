"""
📍 [BOJ] 1715 카드 정렬하기
> [학습 우선순위: Step 1 - 그리디/자료구조]
> 여러 카드 묶음을 합칠 때, 비교 횟수를 최소화하는 방법.

🔍 상세 분석:
- "어떻게 합쳐야 총합이 작아질까?" -> 매 순간마다 **'가장 작은 두 묶음'**을 골라 합치면 됩니다. (이것이 그리디 알고리즘의 핵심!)
- 합쳐진 묶음은 다시 전체 묶음들 사이에 섞여서 다음 비교 대상이 되어야 합니다.
- 매번 최솟값 2개를 뽑아야 하므로 '최소 힙(Min Heap)'을 쓰면 아주 효율적입니다.

🏗️ 구현 체크리스트:
1. 모든 카드 묶음 크기를 힙에 넣는다.
2. 힙에서 가장 작은 것 2개를 꺼낸다 (`heappop` x 2).
3. 두 개를 더하고(`A + B`), 이 결과값을 누적 비용에 더한다.
4. 더한 결과값을 다시 힙에 넣는다 (`heappush`).
5. 힙에 묶음이 딱 1개 남을 때까지 반복한다.

💡 학생 가이드:
- "왜 힙이 필요한가요?" 
  -> 10, 20, 40 묶음이 있을 때 10+20=30을 만들면, 이제 30과 40을 합쳐야 합니다. 이처럼 새로운 값이 계속 생겨나고 그 안에서 다시 최솟값을 찾아야 할 때 힙은 최고의 도구입니다.
"""

import heapq
import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    cards = []
    
    # 모든 카드 묶음을 최소 힙에 담는다
    for _ in range(N):
        heapq.heappush(cards, int(input()))
    
    # 카드 묶음이 1개면 비교할 필요가 없으므로 0 출력
    if len(cards) == 1:
        print(0)
        return
    
    total_cost = 0 # 최종 정답 (비교 횟수 누적)
    
    # 묶음이 1개가 될 때까지 계속 합친다
    while len(cards) > 1:
        # 가장 작은 두 묶음을 꺼낸다
        first = heapq.heappop(cards)
        second = heapq.heappop(cards)
        
        # 두 묶음을 합치는 데 드는 비용
        temp_sum = first + second
        # 누적 비용 합산
        total_cost += temp_sum
        
        # 합쳐진 묶음을 다시 힙에 넣어서 다음 비교에 참여시킨다
        heapq.heappush(cards, temp_sum)
        
    print(total_cost)

if __name__ == "__main__":
    solve()
