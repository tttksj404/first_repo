# 🏆 [A형 백지 정복] 삼성 SW 역량테스트 합격 마스터북 (IM → A형 완전 정복)

이 마스터북은 IM 등급 학생이 **"아무런 힌트 없이 `import sys`부터 500줄 이상의 A형 정답 코드를 100% 스스로 완성"**할 수 있도록 설계된 실전 훈련서입니다. 핀볼, 낚시왕, 마법사 상어, 벽돌 깨기 등 A형의 모든 빈출 유형을 **입력부부터 출력부까지 포함된 코드 전문**과 상세 설계 과정을 통해 기존 대비 10배 이상의 분량으로 해부합니다.

---

## 0. [마인드셋] IM에서 A형으로 가는 징검다리
IM은 **"단순 구현"**입니다. 하지만 A형은 **"정교한 설계"**입니다.
- **IM의 사고**: "한 칸 움직여라? 그럼 `board[r][c]`를 바꾸자."
- **A형의 사고**: "잠깐, 내가 지금 `board[r][c]`를 바꾸면, 아직 움직이지 않은 다른 객체가 내 영향을 받겠지? **복사본(`new_board`)**을 만들거나 **딕셔너리**에 담아서 '동시성'을 확보해야겠어."

---

## 1. [유형 1] 시뮬레이션과 방향 전환 (5650. 핀볼 게임)

### 1-1. [백지 코딩 설계]
1. **데이터 구조**: 웜홀 쌍은 딕셔너리로 저장 `{번호: [(r1, c1), (r2, c2)]}`.
2. **방향 테이블**: 상(0), 하(1), 좌(2), 우(3) 정의 후 1~5번 블록 반사 규칙 리스트화.
3. **엔진**: `while True` 루프 내에서 (1) 벽 충돌 (2) 종료 조건 (3) 블록 (4) 웜홀 (5) 빈 공간 순으로 처리.

### 1-2. [실전 코드 전문] 핀볼 게임 (100% Full Script)
```python
import sys

# 빠른 입력 설정
input = sys.stdin.readline

def solve():
    # 방향 정의: 상(0), 하(1), 좌(2), 우(3)
    dr = [-1, 1, 0, 0]
    dc = [0, 0, -1, 1]
    
    # 1. 방향 전환 테이블 ( change_dir[블록번호][현재방향] = 나갈방향 )
    change_dir = [
        [], 
        [1, 3, 0, 2], # 1번 블록
        [3, 0, 1, 2], # 2번 블록
        [2, 0, 3, 1], # 3번 블록
        [1, 2, 3, 0], # 4번 블록
        [1, 0, 3, 2]  # 5번 블록 (모두 반전)
    ]

    T_str = input().strip()
    if not T_str: return
    T = int(T_str)

    for tc in range(1, T + 1):
        N = int(input().strip())
        board = [list(map(int, input().split())) for _ in range(N)]
        
        # 2. 웜홀 위치 사전 등록 (좌표 검색 최적화)
        wormholes = {}
        for r in range(N):
            for c in range(N):
                val = board[r][c]
                if val >= 6:
                    if val not in wormholes: wormholes[val] = []
                    wormholes[val].append((r, c))

        max_score = 0

        # 3. 모든 시작점 탐색 (0인 곳에서 4방향 발사)
        for r in range(N):
            for c in range(N):
                if board[r][c] != 0: continue
                
                for d in range(4):
                    score = 0
                    cr, cc, cd = r, c, d
                    
                    while True:
                        nr = cr + dr[cd]
                        nc = cc + dc[cd]
                        
                        # 4. 벽 충돌 처리
                        if not (0 <= nr < N and 0 <= nc < N):
                            score += 1
                            cd = [1, 0, 3, 2][cd] # 상하좌우 반전
                            cr, cc = nr, nc
                            continue

                        # 5. 종료 조건 (시작점 복귀 혹은 블랙홀)
                        if (nr == r and nc == c) or board[nr][nc] == -1:
                            if score > max_score:
                                max_score = score
                            break
                        
                        # 6. 블록 충돌
                        if 1 <= board[nr][nc] <= 5:
                            score += 1
                            cd = change_dir[board[nr][nc]][cd]
                            cr, cc = nr, nc
                        
                        # 7. 웜홀 순간이동
                        elif board[nr][nc] >= 6:
                            val = board[nr][nc]
                            # 반대편 구멍으로 좌표 점프
                            if wormholes[val][0] == (nr, nc):
                                cr, cc = wormholes[val][1]
                            else:
                                cr, cc = wormholes[val][0]
                        
                        # 8. 빈 공간 이동
                        else:
                            cr, cc = nr, nc
                            
        print(f"#{tc} {max_score}")

if __name__ == "__main__":
    solve()
```

---

## 2. [유형 2] 속도 최적화와 동시 이동 (17143. 낚시왕)

### 2-1. [백지 코딩 설계]
1. **나머지 연산 최적화**: `speed % (2 * (R-1))` 공식을 사용하지 않으면 시간 초과.
2. **동시성 관리**: 상어가 이동하는 도중에 잡아먹히면 안 되므로 `new_board`를 만들어 이동 결과를 다 담은 뒤 충돌 처리.
3. **데이터 구조**: `sharks = {id: [r, c, s, d, z]}` 딕셔너리로 관리하여 삭제 시 속도 확보.

### 2-2. [실전 코드 전문] 낚시왕 (100% Full Script)
```python
import sys
input = sys.stdin.readline

def solve():
    R, C, M = map(int, input().split())
    if M == 0:
        print(0)
        return

    # sharks[id] = [r, c, s, d, z]
    sharks = {}
    board = [[0] * C for _ in range(R)]
    
    for i in range(1, M + 1):
        r, c, s, d, z = map(int, input().split())
        sharks[i] = [r-1, c-1, s, d, z]
        board[r-1][c-1] = i

    dr = [0, -1, 1, 0, 0] # 상(1), 하(2), 우(3), 좌(4)
    dc = [0, 0, 0, 1, -1]
    
    total_catch = 0

    for fisher_c in range(C):
        # 1. 낚시왕이 상어 잡기
        for r in range(R):
            if board[r][fisher_c] != 0:
                target_id = board[r][fisher_c]
                total_catch += sharks[target_id][4]
                del sharks[target_id]
                board[r][fisher_c] = 0
                break
        
        # 2. 모든 상어 이동
        new_sharks = {}
        new_board = [[0] * C for _ in range(R)]
        
        for s_id, (r, c, s, d, z) in sharks.items():
            # 속도 최적화
            if d <= 2: # 상하
                move_s = s % (2 * (R - 1))
            else: # 좌우
                move_s = s % (2 * (C - 1))
            
            curr_r, curr_c, curr_d = r, c, d
            for _ in range(move_s):
                nr = curr_r + dr[curr_d]
                nc = curr_c + dc[curr_d]
                
                if not (0 <= nr < R and 0 <= nc < C):
                    # 방향 반전
                    if curr_d == 1: curr_d = 2
                    elif curr_d == 2: curr_d = 1
                    elif curr_d == 3: curr_d = 4
                    elif curr_d == 4: curr_d = 3
                    nr = curr_r + dr[curr_d]
                    nc = curr_c + dc[curr_d]
                curr_r, curr_c = nr, nc
            
            # 3. 이동 후 충돌 처리 (가장 큰 상어만 생존)
            if new_board[curr_r][curr_c] == 0:
                new_board[curr_r][curr_c] = s_id
                new_sharks[s_id] = [curr_r, curr_c, s, curr_d, z]
            else:
                exist_id = new_board[curr_r][curr_c]
                if z > new_sharks[exist_id][4]:
                    del new_sharks[exist_id]
                    new_board[curr_r][curr_c] = s_id
                    new_sharks[s_id] = [curr_r, curr_c, s, curr_d, z]
        
        sharks = new_sharks
        board = new_board

    print(total_catch)

if __name__ == "__main__":
    solve()
```

---

## 3. [유형 3] 재귀 탐색과 상태 복구 (5656. 벽돌 깨기)

### 3-1. [백지 코딩 설계]
1. **DFS 구조**: `dfs(count, board)` 형태로 구슬을 떨어뜨린 횟수를 추적.
2. **상태 복구**: 재귀 호출 전 `temp_board = [row[:] for row in board]` 필수.
3. **연쇄 폭발**: BFS를 사용하여 벽돌 숫자만큼 상하좌우 확산 처리.
4. **중력**: 아래에서 위로 읽어 빈 공간 채우기 로직.

### 3-2. [실전 코드 전문] 벽돌 깨기 (100% Full Script)
```python
import sys
from collections import deque

input = sys.stdin.readline

def solve():
    T = int(input())
    for tc in range(1, T + 1):
        N, W, H = map(int, input().split())
        board = [list(map(int, input().split())) for _ in range(H)]
        
        min_bricks = float('inf')

        def count_bricks(arr):
            cnt = 0
            for r in range(H):
                for c in range(W):
                    if arr[r][c] > 0: cnt += 1
            return cnt

        def apply_gravity(arr):
            for c in range(W):
                stack = []
                for r in range(H):
                    if arr[r][c] > 0:
                        stack.append(arr[r][c])
                        arr[r][c] = 0
                for r in range(H-1, -1, -1):
                    if stack: arr[r][c] = stack.pop()
                    else: break

        def bomb(sc, arr):
            # 구슬이 떨어져 처음 만나는 벽돌 찾기
            sr = -1
            for r in range(H):
                if arr[r][sc] > 0:
                    sr = r
                    break
            if sr == -1: return False

            q = deque([(sr, sc, arr[sr][sc])])
            arr[sr][sc] = 0
            
            while q:
                r, c, p = q.popleft()
                if p == 1: continue
                
                for i in range(4):
                    for dist in range(1, p):
                        nr, nc = r + dr[i]*dist, c + dc[i]*dist
                        if 0 <= nr < H and 0 <= nc < W:
                            if arr[nr][nc] > 0:
                                q.append((nr, nc, arr[nr][nc]))
                                arr[nr][nc] = 0
            return True

        dr = [-1, 1, 0, 0]
        dc = [0, 0, -1, 1]

        def dfs(depth, curr_board):
            nonlocal min_bricks
            current_count = count_bricks(curr_board)
            if current_count == 0:
                min_bricks = 0
                return
            if depth == N:
                min_bricks = min(min_bricks, current_count)
                return

            for c in range(W):
                next_board = [row[:] for row in curr_board]
                if bomb(c, next_board):
                    apply_gravity(next_board)
                    dfs(depth + 1, next_board)
                    if min_bricks == 0: return # 가지치기
                else:
                    dfs(depth + 1, next_board)

        dfs(0, board)
        print(f"#{tc} {min_bricks}")

if __name__ == "__main__":
    solve()
```

---

## 4. [유형 4] 복합 객체 시뮬레이션 (20056. 마법사 상어와 파이어볼)

### 4-1. [백지 코딩 설계]
1. **데이터 구조**: `board[r][c] = [[m, s, d], ...]` 3차원 리스트 사용.
2. **이동**: `% N` 연산으로 격자 순환 처리.
3. **상호작용**: 이동이 끝난 후 한 칸에 2개 이상이면 질량/속도/방향 규칙에 따라 분열.

### 4-2. [실전 코드 전문] 파이어볼 (100% Full Script)
```python
import sys
input = sys.stdin.readline

def solve():
    N, M, K = map(int, input().split())
    # r, c, m, s, d
    fireballs = []
    for _ in range(M):
        r, c, m, s, d = map(int, input().split())
        fireballs.append([r-1, c-1, m, s, d])

    dr = [-1, -1, 0, 1, 1, 1, 0, -1]
    dc = [0, 1, 1, 1, 0, -1, -1, -1]

    for _ in range(K):
        # 1. 이동
        new_grid = [[[] for _ in range(N)] for _ in range(N)]
        for r, c, m, s, d in fireballs:
            nr = (r + dr[d] * s) % N
            nc = (c + dc[d] * s) % N
            new_grid[nr][nc].append([m, s, d])

        # 2. 분열 및 합체
        new_fireballs = []
        for r in range(N):
            for c in range(N):
                if len(new_grid[r][c]) == 0: continue
                if len(new_grid[r][c]) == 1:
                    new_fireballs.append([r, c] + new_grid[r][c][0])
                    continue
                
                sum_m, sum_s, cnt = 0, 0, len(new_grid[r][c])
                even, odd = 0, 0
                for m, s, d in new_grid[r][c]:
                    sum_m += m
                    sum_s += s
                    if d % 2 == 0: even += 1
                    else: odd += 1
                
                nm = sum_m // 5
                if nm == 0: continue
                ns = sum_s // cnt
                
                # 방향 결정
                dirs = [0, 2, 4, 6] if even == cnt or odd == cnt else [1, 3, 5, 7]
                for nd in dirs:
                    new_fireballs.append([r, c, nm, ns, nd])
        fireballs = new_fireballs

    print(sum(f[2] for f in fireballs))

if __name__ == "__main__":
    solve()
```

---

## 💡 최종 자가 검증 메커니즘 (Fail-Safe)
1. **입력부**: `sys.stdin.readline`과 `split()`이 정확한가?
2. **초기화**: 매 라운드마다 `new_grid`나 `new_board`를 새로 생성했는가?
3. **인덱스**: `r-1, c-1` 처리를 잊지는 않았는가?
4. **최적화**: `%` 주기 공식과 슬라이싱 복사(`[:]`)를 사용했는가?

---
**이 마스터북의 코드를 백지에 그대로 작성할 수 있다면, 당신은 이미 삼성 A형 취득자입니다.**
