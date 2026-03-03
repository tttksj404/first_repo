"""
📍 [BOJ] 2636 치즈
> [학습 우선순위: Step 3 - BFS/시뮬레이션]
> 공기와 접촉한 치즈의 겉면만 녹는다. 다 녹는 시간과 녹기 직전의 치즈 개수를 구하라.

🔍 상세 분석:
- 이 문제의 트릭은 **'치즈 내부의 구멍'**은 공기가 없어서 안 녹는다는 것입니다.
- 즉, **'바깥쪽 공기'**를 먼저 퍼뜨려야 합니다. 
- (0,0)은 항상 바깥 공기이므로, 여기서부터 BFS를 시작해 '닿는 0'들은 바깥 공기이고, '닿는 1'들은 겉면 치즈가 됩니다.

🏗️ 구현 체크리스트:
1. 매 시간마다 (0,0)에서 출발하는 바깥 공기 탐색 BFS를 돌린다.
2. BFS 도중 치즈(1)를 만나면, 그 치즈를 녹이고(`0`으로 바꾸고) 카운트한다.
3. 주의: 치즈를 만나면 거기서 탐색을 멈춰야 합니다 (그래야 구멍 속 공기까지 안 들어감).
4. 이번 턴에 녹인 치즈가 0개라면 모두 다 녹은 것임!

💡 학생 가이드:
- "공기를 기준으로 보느냐, 치즈를 기준으로 보느냐"의 차이가 승패를 가릅니다. 
- 바깥쪽 공기를 퍼뜨리다가 치즈 벽을 만나면 "아, 이 녀석이 겉면이구나!" 하고 체크하는 방식이 가장 우아합니다.
"""

from collections import deque
import sys
input = sys.stdin.readline

def solve():
    N, M = map(int, input().split())
    board = [list(map(int, input().split())) for _ in range(N)]
    
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    
    def melt_bfs():
        """바깥 공기(0,0)에서 시작해 겉면 치즈를 찾아 녹이는 함수"""
        queue = deque([(0, 0)])
        visited = [[False] * M for _ in range(N)]
        visited[0][0] = True
        
        melted_this_time = 0 # 이번 턴에 녹인 치즈 개수
        
        while queue:
            r, c = queue.popleft()
            
            for i in range(4):
                nr, nc = r + dr[i], c + dc[i]
                
                if 0 <= nr < N and 0 <= nc < M and not visited[nr][nc]:
                    visited[nr][nc] = True # 장부 기록
                    
                    if board[nr][nc] == 0:
                        # 공기면 계속 퍼져나갈 수 있음
                        queue.append((nr, nc))
                    else:
                        # 치즈를 만났다! 겉면이므로 녹인다
                        board[nr][nc] = 0
                        melted_this_time += 1
                        # 중요: 치즈를 녹였으니 이 안쪽으론 공기가 더 못 들어감 (이번 턴에는)
                        
        return melted_this_time

    time_passed = 0 # 걸린 시간
    last_cheese_count = 0 # 녹기 직전 치즈 개수
    
    while True:
        # 1. 이번 턴에 치즈를 녹인다
        res = melt_bfs()
        
        # 2. 만약 녹인 게 0개라면? 다 녹았다는 소리!
        if res == 0:
            break
            
        # 3. 정보 기록 후 다음 시간으로
        last_cheese_count = res
        time_passed += 1
        
    print(time_passed)
    print(last_cheese_count)

if __name__ == "__main__":
    solve()
