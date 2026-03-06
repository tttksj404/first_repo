"""
📍 [BOJ] 2623 음악프로그램
> [학습 우선순위: Step 5 - 그래프/위상정렬+사이클]
> 여러 가수의 출연 순서가 주어질 때 전체 순서를 정하라. 불가능하면 0을 출력하라.

🔍 상세 분석:
- 위상 정렬을 수행하면서 **"사이클(순환)"**이 발생하는지 체크해야 합니다.
- 예: A->B, B->C, C->A 면 서로 기다리다가 아무도 줄을 설 수 없게 됩니다.
- 위상 정렬이 끝났는데 줄 세운 사람의 수가 N보다 작다면? 사이클이 있다는 뜻입니다!

🏗️ 구현 체크리스트:
1. 여러 가수의 순서(`1 4 3`) 입력을 `1->4`, `4->3` 으로 쪼개서 간선을 만든다.
2. 위상 정렬을 돌린다.
3. 결과 리스트의 길이가 N이면 순서를 출력하고, N이 아니면 0을 출력한다.

💡 학생 가이드:
- "왜 결과 리스트 길이가 달라지나요?" 
  -> 사이클에 갇힌 노드들은 진입 차수가 절대 0이 되지 않기 때문에 큐에 아예 들어가지 못합니다. 그래서 결과에서 빠지게 되죠!
"""

from collections import deque
import sys
input = sys.stdin.readline

def solve():
    N, M = map(int, input().split())
    adj = [[] for _ in range(N + 1)]
    indegree = [0] * (N + 1)
    
    for _ in range(M):
        line = list(map(int, input().split()))
        # line[0]은 개수이므로 line[1]부터 실제 순서
        for i in range(1, len(line) - 1):
            u, v = line[i], line[i + 1]
            adj[u].append(v)
            indegree[v] += 1
            
    q = deque()
    for i in range(1, N + 1):
        if indegree[i] == 0:
            q.append(i)
            
    ans = []
    while q:
        curr = q.popleft()
        ans.append(curr)
        for next_node in adj[curr]:
            indegree[next_node] -= 1
            if indegree[next_node] == 0:
                q.append(next_node)
                
    # [사이클 판별]
    # 전체 줄 세운 인원이 N명과 같다면 성공!
    if len(ans) == N:
        for x in ans: print(x)
    else:
        # 그렇지 않으면 사이클 때문에 실패!
        print(0)

if __name__ == "__main__":
    solve()
