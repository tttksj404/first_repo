"""
📍 [BOJ] 1516 게임 개발
> [학습 우선순위: Step 5 - 그래프/위상정렬+DP]
> 각 건물을 짓는 데 필요한 시간과 선수 건물 정보가 주어질 때, 모든 건물의 최소 완성 시간을 구하라.

🔍 상세 분석:
- 1005번(ACM Craft)과 사실상 같은 문제입니다. 
- 입력을 받는 방식만 조금 다르고, 모든 건물에 대한 정답을 출력해야 합니다.

🏗️ 구현 체크리스트:
1. 입력 형식 파싱: `시간 선수1 선수2 ... -1`
2. 위상 정렬 + DP(`max` 갱신) 로직 수행.
3. 1번부터 N번 건물까지 정답 출력.

💡 학생 가이드:
- "DP 점화식의 본질!" 
  -> 어떤 작업이 완료되는 시간은 '나를 위해 선행되어야 할 모든 작업 중 가장 늦게 끝나는 시간'에 '내 소요 시간'을 더한 것입니다.
"""

from collections import deque
import sys
input = sys.stdin.readline

def solve():
    N = int(input())
    adj = [[] for _ in range(N + 1)]
    indegree = [0] * (N + 1)
    build_times = [0] * (N + 1)
    
    # 1. 입력 파싱 및 그래프 구성
    for i in range(1, N + 1):
        line = list(map(int, input().split()))
        build_times[i] = line[0]
        # -1이 나오기 전까지가 선수 건물 번호들
        for pre in line[1:-1]:
            adj[pre].append(i)
            indegree[i] += 1
            
    dp = [0] * (N + 1)
    q = deque()
    
    # 2. 초기 세팅
    for i in range(1, N + 1):
        if indegree[i] == 0:
            q.append(i)
            dp[i] = build_times[i]
            
    # 3. 위상 정렬 + DP
    while q:
        curr = q.popleft()
        for next_node in adj[curr]:
            # 다음 건물의 완성 시간 = max(기존 기록된 시간, 선수건물 완성 시간 + 내 시간)
            dp[next_node] = max(dp[next_node], dp[curr] + build_times[next_node])
            indegree[next_node] -= 1
            if indegree[next_node] == 0:
                q.append(next_node)
                
    for i in range(1, N + 1):
        print(dp[i])

if __name__ == "__main__":
    solve()
