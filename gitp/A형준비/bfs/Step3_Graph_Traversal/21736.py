"""
📍 [BOJ] 21736 헌내기는 친구가 필요해
> [학습 우선순위: Step 3 - BFS/탐색]
> 캠퍼스에서 'I'(도연)가 이동하며 만날 수 있는 모든 'P'(사람)의 수를 구하라.

🔍 상세 분석:
- 전형적인 BFS 탐색 문제입니다. 
- 시작점 'I'의 좌표를 먼저 찾고, 거기서부터 벽('X')을 제외한 통로를 4방향으로 퍼져나가며 'P'를 카운트합니다.

🏗️ 구현 체크리스트:
1. 캠퍼스 지도를 입력받으며 'I'의 시작 좌표 (r, c)를 기록한다.
2. 시작점부터 BFS를 돌린다.
3. 델타 탐색으로 벽('X')이 아닌 곳을 방문하며, 'P'를 만나면 정답 카운트를 올린다.
4. 한 명도 못 만났다면 "TT"를 출력한다.

💡 학생 가이드:
- "만약 친구가 0명이면 어떻게 하나요?" 
  -> 마지막에 `count`가 0인지 체크해서 "TT"라고 따로 출력해주는 조건 분기가 필요합니다. 문제 조건을 잘 읽는 것이 중요해요!
"""

from collections import deque
import sys
input = sys.stdin.readline

def solve():
    # N: 세로, M: 가로
    N, M = map(int, input().split())
    campus = [list(input().strip()) for _ in range(N)]
    
    # 1. 도연이(I)의 위치를 먼저 찾는다
    start_r, start_c = -1, -1
    for r in range(N):
        for c in range(M):
            if campus[r][c] == 'I':
                start_r, start_c = r, c
                break
        if start_r != -1: break
        
    # 2. BFS 탐색 준비
    queue = deque([(start_r, start_c)])
    visited = [[False] * M for _ in range(N)]
    visited[start_r][start_c] = True
    
    friend_count = 0 # 도연이가 만난 친구 수
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    
    # 3. BFS 시작
    while queue:
        r, c = queue.popleft()
        
        for i in range(4):
            nr, nc = r + dr[i], c + dc[i]
            
            # 캠퍼스 내부이면서 아직 안 가본 곳이고, 벽(X)이 아니라면 이동!
            if 0 <= nr < N and 0 <= nc < M and not visited[nr][nc]:
                if campus[nr][nc] != 'X':
                    visited[nr][nc] = True # 방문 체크
                    queue.append((nr, nc)) # 다음 탐색지로 추가
                    
                    # 친구(P)를 만났다면!
                    if campus[nr][nc] == 'P':
                        friend_count += 1
                        
    # 4. 결과 출력
    if friend_count == 0:
        print("TT")
    else:
        print(friend_count)

if __name__ == "__main__":
    solve()
