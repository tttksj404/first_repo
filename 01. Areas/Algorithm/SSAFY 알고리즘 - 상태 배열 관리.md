# 🚀 [백지 코딩 실전] 삼성 A형 합격을 위한 라인 바이 라인 정복 가이드

이 문서는 IM 등급 학생이 **아무런 힌트 없이 `import sys`부터 마지막 `print`까지** 스스로 코드를 짤 수 있게 만들기 위한 **실전 코딩 훈련서**입니다. 이론이 아니라 "실제 코드"와 "설계의 이유"에 집중합니다.

---

## 1. [핀볼 게임 5650] 백지에서 정답까지 (실전 코딩)

핀볼 게임은 코드가 길어 보이지만, **"이동 -> 부딪힘 -> 방향전환"**의 무한 루프만 이해하면 백지에서도 짤 수 있습니다.

### 1단계: 방향 전환 테이블 설계 (뇌를 코드로 옮기기)
가장 먼저 할 일은 `if-else`를 버리는 것입니다. 상(0), 하(1), 좌(2), 우(3)로 방향을 정의하고 테이블을 만드세요.
```python
# change_dir[블록번호][현재방향] = 나갈방향
# 1번 블록: 세모 모양 (빗면이 좌하향)
# - 상(0)으로 오면 하(1)로 반사
# - 하(1)로 오면 우(3)로 꺾임
# - 좌(2)로 오면 상(0)으로 꺾임
# - 우(3)로 오면 좌(2)로 반사
change_dir = [
    [], # 0번 빈 공간
    [1, 3, 0, 2], # 1번 블록
    [3, 0, 1, 2], # 2번 블록
    [2, 0, 3, 1], # 3번 블록
    [1, 2, 3, 0], # 4번 블록
    [1, 0, 3, 2]  # 5번 블록 (모든 방향 반전)
]
```

### 2단계: 핵심 엔진 (While True 루프)
구슬이 블랙홀을 만나거나 제자리로 올 때까지 멈추지 않는 코드입니다.
```python
while True:
    nr, nc = cr + dr[d], cc + dc[d] # 일단 전진
    
    # 1. 벽 충돌 처리 (가장 바깥 경계)
    if not (0 <= nr < N and 0 <= nc < N):
        score += 1
        d = [1, 0, 3, 2][d] # 상하좌우 반전 (0<->1, 2<->3)
        cr, cc = nr, nc # 벽 밖으로 나간 좌표를 일단 현재 좌표로 설정 (다음 턴에 들어옴)
        continue

    # 2. 종료 조건 (가장 중요!)
    if (nr == sr and nc == sc) or board[nr][nc] == -1:
        max_score = max(max_score, score)
        break

    # 3. 블록 충돌
    if 1 <= board[nr][nc] <= 5:
        score += 1
        d = change_dir[board[nr][nc]][d] # 테이블에서 즉시 방향 획득
        cr, cc = nr, nc
    
    # 4. 웜홀 처리
    elif board[nr][nc] >= 6:
        num = board[nr][nc]
        # 현재 좌표가 웜홀 쌍의 0번이면 1번으로, 1번이면 0번으로 순간이동
        target = wormholes[num][1] if wormholes[num][0] == (nr, nc) else wormholes[num][0]
        cr, cc = target # 좌표만 바꾸고 방향(d)은 그대로 유지

    # 5. 빈 공간
    else:
        cr, cc = nr, nc
```

---

## 2. [낚시왕 17143] 속도 최적화와 동시 이동 (실전 코딩)

이 문제는 상어의 속도가 1000이 넘어가므로 **"나머지 연산"** 없이는 절대 합격할 수 없습니다.

### 1단계: 속도 최적화의 정석
상어가 제자리로 돌아오는 주기는 `2 * (격자크기 - 1)` 입니다.
```python
# 상하 이동 시 (R: 행의 개수)
cycle = 2 * (R - 1)
actual_speed = speed % cycle

for _ in range(actual_speed):
    nr = r + dr[d]
    if not (0 <= nr < R): # 경계를 벗어나면
        d = 1 - d # 방향 반전 (0:상, 1:하)
        r += dr[d] # 바뀐 방향으로 한 칸 이동
    else:
        r = nr
```

### 2단계: 상어 잡아먹기 (Concurrency 관리)
모든 상어가 동시에 움직이므로 `new_board`를 사용하는 것이 핵심입니다.
```python
# 1. 이동 후 new_board에 ID를 담는다. (한 칸에 여러 개 가능)
new_board = [[[] for _ in range(C)] for _ in range(R)]
for s_id, shark in sharks.items():
    nr, nc, nd = move(shark)
    new_board[nr][nc].append(s_id)

# 2. 한 칸에 여러 마리면 '가장 큰 놈'만 남기고 딕셔너리에서 지운다.
for r in range(R):
    for c in range(C):
        if len(new_board[r][c]) > 1:
            # 크기(size) 기준 내림차순 정렬
            new_board[r][c].sort(key=lambda x: sharks[x][4], reverse=True)
            winners = new_board[r][c][0]
            losers = new_board[r][c][1:]
            for l_id in losers:
                del sharks[l_id] # 패배한 상어는 영구 삭제
```

---

## 3. [벽돌 깨기 5656] 재귀(DFS) 속의 복사 (실전 코딩)

A형의 꽃은 "상태의 복구"입니다. 구슬을 던지기 전의 판을 기억해야 합니다.

```python
def dfs(depth, current_board):
    global min_bricks
    if depth == N: # N번 구슬을 다 던짐
        min_bricks = min(min_bricks, count_bricks(current_board))
        return

    for col in range(W):
        # 1. [핵심] 현재 판의 복사본을 만든다. (슬라이싱 복사가 deepcopy보다 10배 빠름)
        next_board = [row[:] for row in current_board]
        
        # 2. 벽돌을 깨고(BFS), 중력을 적용한다.
        if bomb(col, next_board): # 벽돌이 하나라도 깨졌다면
            apply_gravity(next_board)
            # 3. 바뀐 판을 들고 다음 구슬 던지러 가기
            dfs(depth + 1, next_board)
        else:
            # 깰 벽돌이 없는 열이면 그냥 다음 구슬로 (Pruning)
            dfs(depth + 1, next_board)
```

---

## 💡 IM 학생을 위한 최종 체크리스트 (백지 코딩 전용)
- [ ] **초기화 위치**: `visited` 배열이나 `new_board`를 루프 **안**에서 초기화했는가? (매 턴마다 새로워야 함)
- [ ] **인덱스 범위**: `nr, nc` 체크 시 `0 <= nr < N` 범위를 정확히 지켰는가?
- [ ] **종료 조건**: 핀볼의 '시작점 복귀'나 상어의 '낚시꾼 이동' 순서를 문제대로 지켰는가?
- [ ] **나머지 연산**: 상어 속도 최적화 수식 `speed % (2 * (N - 1))`을 외웠는가?

---
**관련 문제**: [[핀볼_게임_실전코드]] | [[낚시왕_상어_최적화]] | [[벽돌깨기_재귀마스터]]
**태그**: #비트마스크 #튜링기계상태 #ssafy_알고리즘 #삼성_a형_백지코딩
