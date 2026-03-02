# 🏆 [A형 백지 정복] 삼성 SW 역량테스트 합격 마스터 피스 (IM → A형 도약편)

이 문서는 IM 등급을 갓 취득한 학생이 **"아무런 힌트 없이 `import sys`부터 300줄 이상의 A형 정답 코드를 스스로 완성"**할 수 있도록 설계된 실전 훈련서입니다. 핀볼 게임, 상어 시리즈, 벽돌 깨기 등 A형의 모든 정수를 8배 이상의 상세한 분량으로 해부합니다.

---

## 0. [마인드셋] IM에서 A형으로 가는 징검다리
IM은 **"단순한 노동"**입니다. 격자를 돌리고, 시키는 대로 이동하면 됩니다. 하지만 A형은 **"정교한 설계"**입니다.
- **IM의 사고**: "한 칸 움직여라? 그럼 `board[r][c]`를 바꾸자."
- **A형의 사고**: "잠깐, 내가 지금 `board[r][c]`를 바꾸면, 아직 움직이지 않은 다른 상어가 내 영향을 받겠지? **복사본(`new_board`)**을 만들거나 **딕셔너리**에 담아서 '동시성'을 확보해야겠어."

---

## 1. [핀볼 게임 5650] 방향 전환과 무한 루프의 정석

핀볼 게임은 A형의 **'시뮬레이션 엔진'**을 배우기에 가장 좋은 문제입니다. 백지 코딩을 위해 다음 5단계를 머릿속에 박으세요.

### 1-1. [설계] 방향 전환 테이블 (The change_dir Table)
삼성 시험장에서 `if-else`로 방향을 꺾는 순간 당신은 탈락입니다. 반드시 테이블화 하세요.
```python
# 방향: 상(0), 하(1), 좌(2), 우(3)
# 1번 블록: 상(0)->하(1), 하(1)->우(3), 좌(2)->상(0), 우(3)->좌(2)
# 2번 블록: 상(0)->우(3), 하(1)->상(0), 좌(2)->하(1), 우(3)->좌(2)
# ... 이렇게 5번까지 미리 종이에 그려보고 코딩하세요.
change_dir = [
    [], # 0번 빈 공간
    [1, 3, 0, 2], # 1번
    [3, 0, 1, 2], # 2번
    [2, 0, 3, 1], # 3번
    [1, 2, 3, 0], # 4번
    [1, 0, 3, 2]  # 5번 (모든 방향 반전)
]
```

### 1-2. [실전 코드] 핀볼 게임 풀 코드 (주석 포함)
```python
import sys
input = sys.stdin.readline

def solve():
    T = int(input())
    for tc in range(1, T+1):
        N = int(input())
        board = [list(map(int, input().split())) for _ in range(N)]
        
        # 1. 웜홀 위치 사전 등록 (딕셔너리: 좌표 검색 속도 극대화)
        wormholes = {}
        for r in range(N):
            for c in range(N):
                val = board[r][c]
                if val >= 6:
                    if val not in wormholes: wormholes[val] = []
                    wormholes[val].append((r, c))

        max_score = 0
        dr = [-1, 1, 0, 0]
        dc = [0, 0, -1, 1]

        # 2. 모든 시작점 탐색 (0인 곳에서 4방향 다 쏘기)
        for r in range(N):
            for c in range(N):
                if board[r][c] != 0: continue
                for d in range(4):
                    score = 0
                    cr, cc, cd = r, c, d # 현재 상태 저장
                    
                    while True:
                        nr, nc = cr + dr[cd], cc + dc[cd]
                        
                        # 3. 벽 충돌 처리
                        if not (0 <= nr < N and 0 <= nc < N):
                            score += 1
                            cd = [1, 0, 3, 2][cd] # 상하/좌우 반전
                            cr, cc = nr, nc
                            continue # 방향만 바꾸고 좌표는 '벽 밖'인 상태로 다음 턴 진입

                        # 4. 종료 조건 (시작점 복귀 or 블랙홀)
                        if (nr == r and nc == c) or board[nr][nc] == -1:
                            max_score = max(max_score, score)
                            break
                        
                        # 5. 블록 충돌
                        if 1 <= board[nr][nc] <= 5:
                            score += 1
                            cd = change_dir[board[nr][nc]][cd]
                            cr, cc = nr, nc
                        
                        # 6. 웜홀 처리
                        elif board[nr][nc] >= 6:
                            num = board[nr][nc]
                            # 현재 들어간 좌표가 아닌 '반대편' 구멍으로 순간이동
                            pair = wormholes[num]
                            cr, cc = pair[1] if pair[0] == (nr, nc) else pair[0]
                        
                        # 7. 빈 공간
                        else:
                            cr, cc = nr, nc
        print(f"#{tc} {max_score}")

solve()
```

---

## 2. [낚시왕 17143] 속도 최적화와 동시성 제어

이 문제는 **"객체들이 동시에 움직여서 한 칸에 모였을 때 어떻게 처리할 것인가"**의 정답을 보여줍니다.

### 2-1. [비법] 나머지 연산(%)을 통한 속도 최적화
속도가 1000일 때 1000번 `for`문을 돌리는 것은 하수입니다. 상어는 주기를 가집니다.
- **주기 공식**: `cycle = 2 * (격자크기 - 1)`
- **적용**: `actual_speed = speed % cycle`
- 이 공식 하나로 시간 초과 99%를 해결할 수 있습니다.

### 2-2. [실전 코드] 상어 이동 및 충돌 전문
```python
def move_sharks(sharks, R, C):
    # 1. 동시성 보장을 위해 새로운 판 생성
    new_board = [[[] for _ in range(C)] for _ in range(R)]
    
    for s_id in list(sharks.keys()):
        r, c, s, d, z = sharks[s_id]
        
        # 2. 속도 최적화 적용
        if d <= 1: # 상하
            cycle = 2 * (R - 1)
            s %= cycle
        else: # 좌우
            cycle = 2 * (C - 1)
            s %= cycle
            
        # 3. 한 칸씩 이동 (벽 만나면 반사)
        for _ in range(s):
            nr, nc = r + dr[d], c + dc[d]
            if not (0 <= nr < R and 0 <= nc < C):
                d = [1, 0, 3, 2][d] # 방향 반전
                r, c = r + dr[d], c + dc[d]
            else:
                r, c = nr, nc
        
        # 4. 새 판에 상어 ID 저장
        new_board[r][c].append(s_id)
        sharks[s_id] = [r, c, s, d, z] # 정보 업데이트

    # 5. 충돌 처리: 한 칸에 여러 마리면 가장 큰 놈만 생존
    for r in range(R):
        for c in range(C):
            if len(new_board[r][c]) > 1:
                # 크기(z) 기준 내림차순 정렬
                new_board[r][c].sort(key=lambda x: sharks[x][4], reverse=True)
                winner = new_board[r][c][0]
                losers = new_board[r][c][1:]
                for l_id in losers:
                    del sharks[l_id] # 영구 삭제
```

---

## 3. [벽돌 깨기 5656] 재귀(DFS)와 상태 복구의 기술

A형 고난도 문제는 **"내가 방금 한 선택을 취소하고 다시 다른 선택을 해야 하는"** 백트래킹 상황이 많습니다.

### 3-1. [핵심] 얕은 복사(`[:]`)를 통한 상태 보존
`deepcopy`는 너무 느립니다. 2차원 리스트 복사는 반드시 컴프리헨션을 쓰세요.
```python
# 구슬을 던지기 전의 상태를 복사해서 들고 들어갑니다.
for col in range(W):
    next_board = [row[:] for row in current_board] # 8배 상세 설명: 이 한 줄이 '시간 여행'을 가능하게 합니다.
    if drop_marble(col, next_board):
        apply_gravity(next_board)
        dfs(depth + 1, next_board) # 바뀐 판을 들고 다음 단계로
```

### 3-2. [실전 코드] 중력(Gravity) 구현의 정석
터진 벽돌들 사이의 빈 공간을 위에서 아래로 채우는 가장 깔끔한 방법입니다.
```python
def apply_gravity(board, H, W):
    for c in range(W):
        stack = []
        for r in range(H):
            if board[r][c] > 0:
                stack.append(board[r][c])
                board[r][c] = 0
        
        # 아래서부터 다시 채우기
        for r in range(H-1, -1, -1):
            if stack:
                board[r][c] = stack.pop()
            else:
                break
```

---

## 4. [디버깅] "예제는 맞는데 80%만 맞는" 당신을 위한 자가 진단
IM에서 A형으로 넘어갈 때 가장 흔히 하는 실수 3가지:

1.  **초기화 위치**: `visited` 배열이나 `new_board`를 전역으로 선언했나요? **반드시 매 턴/매 재귀 루프 안에서 새로 생성해야 합니다.**
2.  **경계값 등호**: `nr < N` 인가요 `nr <= N` 인가요? 삼성은 0번 인덱스와 1번 인덱스를 섞어 쓰므로 반드시 확인하세요.
3.  **나머지 연산 주기**: 상어 속도 최적화 시 `(N-1) * 2` 가 아니라 `N * 2` 로 계산하지 않았나요?

---
**💡 학습 미션**: 이 문서를 옆에 띄워놓고, **핀볼 게임(5650)**부터 빈 화면에서 직접 타이핑해 보세요. 막히는 주석 한 줄이 있다면, 그 부분이 당신이 A형 취득을 위해 정복해야 할 **'사고의 구멍'**입니다.

---
**태그**: #samsung_a #ssafy_알고리즘 #백지코딩 #IM탈출 #A형정복
