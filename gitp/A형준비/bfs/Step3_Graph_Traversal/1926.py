"""
📍 [BOJ] 1926 그림
> [학습 우선순위: Step 3 - BFS/영역찾기]
> 1로 표시된 그림들의 개수와 그중 가장 큰 그림의 넓이를 구하라.

🔍 상세 분석:
- '연결된 덩어리'를 찾는 전형적인 BFS 문제의 교과서입니다.
- 지도 전체를 돌며 '1'이고 아직 '방문 안 한' 곳을 찾으면, 거기서부터 BFS를 시작해 그 덩어리를 싹 훑습니다.
- BFS가 한 번 끝날 때마다 '그림 1개'를 찾은 것이고, 훑은 칸의 개수가 '넓이'가 됩니다.

🏗️ 구현 체크리스트:
1. `visited` 배열로 중복 탐색을 막는다.
2. 상하좌우 탐색을 위해 델타 변수(`dr`, `dc`)를 만든다.
3. 큐(`deque`)를 활용해 연결된 1을 모두 찾아나간다.
4. 영역의 크기를 계산하여 최댓값을 갱신한다.

💡 학생 가이드:
- "델타 탐색(`dr`, `dc`)이 뭔가요?" 
  -> 현재 위치 (r, c)에서 위(r-1, c), 아래(r+1, c), 왼쪽(r, c-1), 오른쪽(r, c+1)을 확인하기 위해 미리 더할 값들을 리스트로 만들어둔 것입니다. 모든 격자 문제의 기본입니다!
"""

from collections import deque
import sys
input = sys.stdin.readline

def solve():
    # n: 세로, m: 가로 크기
    n, m = map(int, input().split())
    # 도화지 정보 입력
    grid = [list(map(int, input().split())) for _ in range(n)]
    # 방문 장부 (갔던 곳은 다시 안 가도록)
    visited = [[False] * m for _ in range(n)]
    
    total_paintings = 0 # 그림의 개수
    max_area = 0 # 가장 넓은 그림의 크기
    
    # 상, 하, 좌, 우 델타 이동 설정
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    
    def bfs(r, c):
        """(r, c)부터 연결된 모든 '1'을 찾아 넓이를 반환하는 함수"""
        queue = deque([(r, c)])
        visited[r][c] = True
        area = 1 # 시작점도 넓이에 포함
        
        while queue:
            curr_r, curr_c = queue.popleft()
            
            # 현재 위치에서 4방향을 찔러본다
            for i in range(4):
                nr, nc = curr_r + dr[i], curr_c + dc[i]
                
                # 1. 도화지 범위를 벗어나지 않고
                # 2. 아직 방문하지 않았으며
                # 3. 그곳이 그림(1)이라면
                if 0 <= nr < n and 0 <= nc < m and not visited[nr][nc]:
                    if grid[nr][nc] == 1:
                        visited[nr][nc] = True # 장부에 도장 찍고
                        queue.append((nr, nc)) # 큐에 넣어서 다음 탐색지로 설정
                        area += 1 # 넓이 1 증가
        return area

    # 도화지 모든 칸을 하나씩 순회
    for r in range(n):
        for c in range(m):
            # 그림이 있고(1), 아직 방문 안 한 곳을 발견하면!
            if grid[r][c] == 1 and not visited[r][c]:
                # 1. 새로운 그림을 하나 찾음
                total_paintings += 1
                # 2. 이 그림의 넓이를 BFS로 구함
                current_area = bfs(r, c)
                # 3. 지금까지 본 것 중 가장 큰지 확인
                max_area = max(max_area, current_area)
                
    # 최종 결과 출력
    print(total_paintings)
    print(max_area)

if __name__ == "__main__":
    solve()
