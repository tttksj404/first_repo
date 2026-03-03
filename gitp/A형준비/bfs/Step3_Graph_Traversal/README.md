# Step 3: 그래프 탐색(BFS/DFS) 마스터 가이드

이 단계의 목표는 격자판이나 노드 연결 관계를 빠짐없이 탐색하는 코드를 기계처럼 짜는 것입니다.

### 1. 격자판 탐색의 만능 템플릿 (BFS)

삼성 A형의 단골 유형인 격자(Grid) 문제는 아래 템플릿으로 90% 이상 해결됩니다.

```python
from collections import deque

def bfs(start_r, start_c):
    # 1. 큐와 방문 기록부(visited) 준비
    queue = deque([(start_r, start_c)])
    visited[start_r][start_c] = True

    # 2. 상하좌우 델타 이동 설정
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]

    while queue:
        # 3. 현재 위치 꺼내기
        r, c = queue.popleft()

        # 4. 4방향으로 다음 위치 탐색
        for i in range(4):
            nr, nc = r + dr[i], c + dc[i]

            # 5. 다음 위치가 유효한지 체크
            if 0 <= nr < N and 0 <= nc < M and not visited[nr][nc]:
                if grid[nr][nc] == 1: # 문제의 조건 (예: 길인가?)
                    # 6. 방문 처리 후 큐에 삽입
                    visited[nr][nc] = True
                    queue.append((nr, nc))
```
- **예시**: 1926번 (그림), 21736번 (헌내기)

### 2. DFS vs BFS: 언제 무엇을 쓸까?

- **DFS (깊이 우선 탐색)**
  - **언제?**: "경로의 존재 여부", "연결된 모든 것 찾기" 등 끝까지 가봐야 아는 문제.
  - **구현**: 재귀 함수.
  - **특징**: 스택 오버플로우 주의 (`sys.setrecursionlimit`).

- **BFS (너비 우선 탐색)**
  - **언제?**: **"최단 거리/최소 시간"** (단, 모든 간선 가중치가 1일 때).
  - **구현**: 큐(`deque`).
  - **특징**: 거리별로 탐색하므로 가장 먼저 도착한 것이 곧 최단 경로임. (예: 18352번)

### 3. 트리 순회 3대장

- **전위(Pre-order)**: `나 -> 왼 -> 오` (루트를 먼저 방문)
- **중위(In-order)**: `왼 -> 나 -> 오` (BST에서 오름차순 정렬됨)
- **후위(Post-order)**: `왼 -> 오 -> 나` (자식들을 먼저 방문)
- **예시**: 1991번 (트리 순회)
- 이 3가지 순회 방식은 재귀 함수에서 `print(나)`문의 위치만 바꾸면 됩니다.
