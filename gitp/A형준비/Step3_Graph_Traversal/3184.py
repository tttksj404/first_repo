"""
📍 [BOJ] 3184 양
> [학습 우선순위: Step 3 - BFS/영역비교]
> 울타리로 구분된 각 영역에서 양과 늑대의 숫자를 비교해 생존자를 결정하라.

🔍 상세 분석:
- '1926 그림' 문제와 아주 유사하지만, 덩어리만 찾는 게 아니라 그 안의 '동물 숫자'를 세야 합니다.
- 양이 늑대보다 많으면 양만 살아남고, 늑대가 양보다 많거나 같으면 늑대만 살아남습니다.
- 전체를 돌며 영역 하나를 끝낼 때마다 살아남은 마릿수를 전체 변수에 누적합니다.

🏗️ 구현 체크리스트:
1. `visited` 배열로 방문 여부 관리.
2. 전체 지도를 돌며 `.` (공간)이나 `v` (늑대), `o` (양)를 만났는데 방문 안 했으면 BFS 시작.
3. BFS 내부에서 양의 수(`s`)와 늑대의 수(`w`)를 카운트한다.
4. BFS 종료 시점에 `s`와 `w`를 비교하여 더 많은 쪽만 전체 결과에 더한다.

💡 학생 가이드:
- "울타리(`#`)는 어떻게 처리하나요?" 
  -> 울타리는 벽입니다. BFS가 퍼져나갈 때 `if board[nr][nc] != '#'` 조건을 걸어 울타리를 넘지 못하게 하면 자연스럽게 영역이 구분됩니다.
"""

from collections import deque
import sys
input = sys.stdin.readline

def solve():
    R, C = map(int, input().split())
    board = [list(input().strip()) for _ in range(R)]
    visited = [[False] * C for _ in range(R)]
    
    total_sheep = 0 # 최종 살아남은 양
    total_wolves = 0 # 최종 살아남은 늑대
    
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    
    def bfs(r, c):
        """한 영역을 훑으며 양(s_cnt)과 늑대(w_cnt)의 수를 세는 함수"""
        q = deque([(r, c)])
        visited[r][c] = True
        s_cnt, w_cnt = 0, 0
        
        while q:
            curr_r, curr_c = q.popleft()
            
            # 현재 칸의 정체 확인
            if board[curr_r][curr_c] == 'o': 
                s_cnt += 1
            elif board[curr_r][curr_c] == 'v': 
                w_cnt += 1
            
            # 주변으로 영역 확장
            for i in range(4):
                nr, nc = curr_r + dr[i], curr_c + dc[i]
                if 0 <= nr < R and 0 <= nc < C and not visited[nr][nc]:
                    # 울타리가 아니라면 영역이 이어져 있는 것임
                    if board[nr][nc] != '#':
                        visited[nr][nc] = True
                        q.append((nr, nc))
        return s_cnt, w_cnt

    # 지도 전체 탐색
    for r in range(R):
        for c in range(C):
            # 울타리가 아니고, 아직 방문 안 한 칸이면 새로운 영역 탐색 시작!
            if board[r][c] != '#' and not visited[r][c]:
                s, w = bfs(r, c)
                
                # [생존자 결정]
                # 1. 양이 늑대보다 많으면 양이 늑대를 쫓아냄
                if s > w:
                    total_sheep += s
                # 2. 늑대가 양보다 많거나 같으면 양이 모두 잡아먹힘
                else:
                    total_wolves += w
                    
    # 결과 출력
    print(total_sheep, total_wolves)

if __name__ == "__main__":
    solve()
