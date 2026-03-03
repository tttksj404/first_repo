"""
📍 [BOJ] 14889 스타트와 링크
> [학습 우선순위: Step 2 - 백트래킹/팀나누기]
> N명의 사람을 N/2명씩 두 팀으로 나눌 때, 두 팀의 능력치 차이의 최솟값을 구하라.

🔍 상세 분석:
- N명 중에서 N/2명을 뽑는 '조합' 문제입니다.
- 내가 '스타트 팀'으로 선택되면(`visited[i] = True`), 선택되지 않은 나머지 사람들은 자동으로 '링크 팀'이 됩니다.
- N이 최대 20이므로, 최대 20C10 = 184,756가지 경우의 수를 전부 따져볼 수 있습니다.

🏗️ 구현 체크리스트:
1. `visited` 배열로 팀원 선택 여부를 체크한다.
2. DFS 함수에서 현재까지 뽑은 인원수(`count`)와 다음 선택할 시작점(`idx`)을 관리한다.
3. N/2명을 다 뽑으면, 각 팀의 점수를 계산한다.
   - 팀 점수 = 같은 팀원 i, j 쌍에 대해 `S[i][j] + S[j][i]`를 모두 더한 값.
4. 두 팀의 점수 차이의 최댓값을 갱신한다.

💡 학생 가이드:
- "점수 계산할 때 왜 이중 for문을 쓰나요?" 
  -> 같은 팀 안에 (A, B, C)가 있다면, (A,B), (B,A), (A,C), (C,A), (B,C), (C,B) 모든 경우의 능력치를 더해줘야 하기 때문입니다.
"""

import sys
input = sys.stdin.readline

N = int(input())
# 능력치 시너지 행렬 S
S = [list(map(int, input().split())) for _ in range(N)]

# 방문 장부: True면 스타트 팀, False면 링크 팀
visited = [False] * N
min_diff = float('inf') # 정답 (최소 차이)

def calculate():
    """현재 팀 구성에 따른 점수 차이 계산 함수"""
    start_score = 0
    link_score = 0
    
    # 0번부터 N-1번까지 모든 쌍(i, j)을 조사
    for i in range(N):
        for j in range(i + 1, N):
            # i와 j가 둘 다 스타트 팀(True)이라면
            if visited[i] and visited[j]:
                start_score += S[i][j] + S[j][i]
            # i와 j가 둘 다 링크 팀(False)이라면
            elif not visited[i] and not visited[j]:
                link_score += S[i][j] + S[j][i]
                
    return abs(start_score - link_score)

def dfs(count, idx):
    """
    count: 현재 스타트 팀에 합류한 사람 수
    idx: 이번에 합류시킬 후보 사람 번호
    """
    global min_diff
    
    # [기저 조건] 한 팀에 N/2명이 다 찼을 때
    if count == N // 2:
        diff = calculate()
        min_diff = min(min_diff, diff)
        return

    # [유도 파트] 사람 i를 팀에 넣거나 안 넣거나
    for i in range(idx, N):
        if not visited[i]:
            # 1. i를 스타트 팀에 넣는다
            visited[i] = True
            # 2. 다음 사람을 뽑으러 간다 (중복 방지 위해 i+1 전달)
            dfs(count + 1, i + 1)
            # 3. 중요!! 다음 경우의 수를 위해 i를 다시 팀에서 뺀다 (백트래킹)
            visited[i] = False
            
            # [최적화] 차이가 0이면 더 볼 필요 없음
            if min_diff == 0:
                return

# 0명을 뽑은 상태에서 0번 사람부터 탐색 시작
dfs(0, 0)
print(min_diff)
