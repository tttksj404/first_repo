# 🧠 삼성 A형 합격 마스터 Codex (암기용 최종 요약본)

이 문서는 삼성 SW 역량테스트 A형(Advanced) 합격을 위한 **'단 하나의 문서'**입니다. 오늘 하루 동안 이 Codex의 모든 패턴을 백지에 그대로 타이핑할 수 있도록 암기하세요. 최신 3개년 기출(마법사 상어, 주사위 굴리기, 핀볼 등)의 모든 핵심 로직이 이 안에 담겨 있습니다.

---

## 0. [필승 전략] 삼성 A형 3계명
1. **[설계 20분]**: 코딩 전 종이에 **데이터 구조(Dict vs List)**와 **실행 순서**를 100% 확정한다.
2. **[동시성 제어]**: "객체가 동시에 이동"하면 무조건 `new_board` 또는 `temp_dict`에 담고 한꺼번에 갱신한다.
3. **[디버깅 출력]**: 막히면 즉시 `print_grid()`를 호출하여 격자 상태를 눈으로 확인한다.

---

## 1. [엔진] 기본 설정 및 디버깅 유틸
```python
import sys
from collections import deque
input = sys.stdin.readline
sys.setrecursionlimit(10**6)

# [디버깅] 격자 출력 함수 (제출 시 주석 처리 필수)
def print_grid(grid, msg=""):
    print(f"--- {msg} ---")
    for row in grid:
        print(" ".join(f"{str(x):>3}" for x in row))
    print("-" * 20)

# [방향] 상(0), 하(1), 좌(2), 우(3) - 반전: d^1 (01, 23 관계일 때)
dr = [-1, 1, 0, 0]
dc = [0, 0, -1, 1]
```

---

## 2. [시뮬레이션] 핵심 조작 패턴

### 2-1. 방향 전환 테이블 (핀볼/반사)
`if-else` 대신 테이블을 사용해 실수를 방지합니다.
```python
# change_dir[블록번호][현재방향] = 나갈방향
# 상(0), 하(1), 좌(2), 우(3)
change_dir = [
    [], 
    [1, 3, 0, 2], # 1번 블록
    [3, 0, 1, 2], # 2번 블록
    [2, 0, 3, 1], # 3번 블록
    [1, 2, 3, 0], # 4번 블록
    [1, 0, 3, 2]  # 5번 블록 (모두 반전)
]
```

### 2-2. 속도 최적화와 주기 (%)
```python
# 상하 주기: 2*(R-1), 좌우 주기: 2*(C-1)
# N-1칸 갔다가 N-1칸 돌아오면 제자리
actual_s = s % (2 * (N - 1)) 
```

### 2-3. 주사위 굴리기 (Dice Roll)
```python
# u, d, f, b, l, r = 위, 아래, 앞, 뒤, 왼쪽, 오른쪽
def roll_east(u, d, f, b, l, r):
    return l, r, f, b, d, u # 동쪽으로 굴리면 위->오른쪽, 오른쪽->아래...
def roll_north(u, d, f, b, l, r):
    return f, b, d, u, l, r # 북쪽으로 굴리면 위->뒤, 뒤->아래...
```

---

## 3. [BFS/DFS] 탐색 및 백트래킹

### 3-1. 우선순위 BFS (아기 상어)
```python
def find_target(sr, sc):
    q = deque([(sr, sc, 0)])
    visited = [[-1] * N for _ in range(N)]
    visited[sr][sc] = 0
    candidates = []
    min_dist = float('inf')

    while q:
        r, c, d = q.popleft()
        if d >= min_dist: continue
        
        for i in range(4):
            nr, nc = r + dr[i], c + dc[i]
            if 0 <= nr < N and 0 <= nc < N and visited[nr][nc] == -1:
                if can_pass(nr, nc):
                    visited[nr][nc] = d + 1
                    if is_target(nr, nc):
                        min_dist = d + 1
                        candidates.append((d+1, nr, nc))
                    q.append((nr, nc, d + 1))
    
    return sorted(candidates)[0] if candidates else None
```

### 3-2. 백트래킹 상태 복구 (연구소/벽돌깨기)
```python
def dfs(depth, board):
    if depth == M:
        return calculate(board)
    
    # 2차원 리스트 복사 (타임머신)
    temp_board = [row[:] for row in board]
    # ... 변형 로직 ...
    dfs(depth + 1, temp_board)
    # 복구할 필요 없이 temp_board를 버리면 됨 (재귀의 정석)
```

---

## 4. [격자 제어] 고급 테크닉

### 4-1. 90도 회전 및 부분 회전
```python
# 전체 90도 회전: (r, c) -> (c, N-1-r)
def rotate_90(grid):
    return [list(row) for row in zip(*grid[::-1])]

# 부분 격자 회전 (r, c 시작, size 크기)
def rotate_sub(r, c, size):
    sub = [row[c:c+size] for row in board[r:r+size]]
    rotated = rotate_90(sub)
    for i in range(size):
        board[r+i][c:c+size] = rotated[i]
```

### 4-2. 중력 (Gravity)
```python
def apply_gravity():
    for c in range(N):
        idx = N - 1 # 아래서부터 채울 위치
        for r in range(N-1, -1, -1):
            if board[r][c] > 0:
                board[idx][c], board[r][c] = board[r][c], board[idx][c]
                if idx != r: board[r][c] = 0 # 원래 위치 비우기
                idx -= 1
```

### 4-3. 달팽이/토네이도 (Spiral)
```python
def tornado(sr, sc):
    r, c = sr, sc
    d, dist = 0, 1
    while True:
        for _ in range(2): # 1,1, 2,2, 3,3 ... 거리만큼 두 번씩 방향 전환
            for _ in range(dist):
                r, c = r + dr[d], c + dc[d]
                if (r, c) == (0, -1): return # 종료
                # ... 로직 수행 ...
            d = (d + 1) % 4
        dist += 1
```

---

## 5. [객체 관리] 딕셔너리(`dict`) 전략
한 칸에 여러 객체가 모일 때(파이어볼 등) 격자보다 딕셔너리가 유리합니다.
```python
# 이동 단계
new_objects = {}
for (r, c), items in objects.items():
    for m, s, d in items:
        nr, nc = (r + dr[d]*s)%N, (c + dc[d]*s)%N
        if (nr, nc) not in new_objects: new_objects[(nr, nc)] = []
        new_objects[(nr, nc)].append([m, s, d])

# 상호작용 단계
for (r, c), items in new_objects.items():
    if len(items) >= 2:
        # 질량 합산 / 분열 로직 수행
```

---

## 🩺 실전 검증 리스트 (Final Check)
- [ ] **데이터 초기화**: 매 턴마다 `new_board`, `visited`를 새로 생성했는가?
- [ ] **인덱스**: `1-based` 좌표를 `0-based`로 잘 변환했는가?
- [ ] **방향**: 반전 및 회전 인덱스가 문제 조건과 일치하는가?
- [ ] **가치지기**: DFS에서 이미 최솟값을 넘었다면 `return` 하는가?
- [ ] **복합 로직**: 이동 -> 폭발 -> 중력 -> 회전 등의 순서가 정확한가?

---
**이 Codex의 코드를 머릿속이 아닌 손가락이 기억하게 만드세요. 그것이 A형 합격의 유일한 길입니다.**
