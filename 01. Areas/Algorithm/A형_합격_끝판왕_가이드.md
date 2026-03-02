# 🏆 삼성 A형 합격 끝판왕 가이드: 백지 코딩 실전 훈련서 (5배 분량)

이 문서는 IM 등급 학생이 **"아무런 힌트 없이 `import sys`부터 핀볼 게임 전체 코드를 스스로 완성"**할 수 있도록 설계된 실전형 가이드입니다. 

---

## 1. [핀볼 게임 5650] 백지 정복: 사고의 흐름과 풀 코드

### 1.1 설계의 핵심: "방향 테이블" (Brain to Code)
A형은 1~5번 블록마다 꺾이는 방향을 `if-else`로 짜면 무조건 틀립니다. 아래 테이블을 외우고 코딩을 시작하세요.
- **방향 정의**: 상(0), 하(1), 좌(2), 우(3)
```python
# change_dir[블록번호][현재방향] = 나갈방향
# 1번 블록: 상(0)->하(1), 하(1)->우(3), 좌(2)->상(0), 우(3)->좌(2)
change_dir = [
    [], # 0번 (빈 공간)
    [1, 3, 0, 2], # 1번 블록
    [3, 0, 1, 2], # 2번 블록
    [2, 0, 3, 1], # 3번 블록
    [1, 2, 3, 0], # 4번 블록
    [1, 0, 3, 2]  # 5번 블록 (모든 방향 반전)
]
```

### 1.2 웜홀 처리 (Dictionary 활용)
웜홀은 쌍으로 존재하므로, 입력을 받을 때 미리 좌표를 저장해 둡니다.
```python
wormholes = {}
for r in range(N):
    for c in range(N):
        val = board[r][c]
        if val >= 6:
            if val not in wormholes: wormholes[val] = []
            wormholes[val].append((r, c)) # 쌍으로 저장
```

### 1.3 전체 코드의 정석 (Skeleton)
```python
while True:
    nr, nc = cr + dr[d], cc + dc[d] # 전진
    
    # 1. 벽 충돌 (가장 바깥)
    if not (0 <= nr < N and 0 <= nc < N):
        score += 1
        d = [1, 0, 3, 2][d] # 반전
        cr, cc = nr, nc
        continue

    # 2. 종료 조건
    if (nr == sr and nc == sc) or board[nr][nc] == -1:
        max_score = max(max_score, score)
        break

    # 3. 블록 충돌
    if 1 <= board[nr][nc] <= 5:
        score += 1
        d = change_dir[board[nr][nc]][d]
        cr, cc = nr, nc
    
    # 4. 웜홀 순간이동
    elif board[nr][nc] >= 6:
        # 다른 구멍으로 순간이동
        pair = wormholes[board[nr][nc]]
        cr, cc = pair[1] if pair[0] == (nr, nc) else pair[0]
```

---

## 2. [낚시왕 17143] 속도 최적화: 나머지 연산의 마법 (%)
상어 속도가 1000이라면, `s % (2 * (N-1))` 수식을 사용해야 합니다.
- **주기**: `(N-1) * 2` 칸을 가면 제자리로 돌아옵니다.
- **백지 코딩 팁**: `s %= (2 * (N-1))` 을 무조건 외우고 시작하세요.

---

## 3. [동시 이동] `new_board` 전략
"모든 상어가 동시에 움직인다"면, 반드시 이동 결과를 **새로운 판**에 담은 뒤 한꺼번에 덮어씌워야 합니다.
```python
# 1. 새 판에 담기
new_board = [[[] for _ in range(C)] for _ in range(R)]
for s_id in sharks:
    nr, nc, nd = move_shark(sharks[s_id])
    new_board[nr][nc].append(s_id)

# 2. 중복 칸에서 큰 놈만 남기기
for r in range(R):
    for c in range(C):
        if len(new_board[r][c]) > 1:
            # size 기준 정렬하여 1등만 남김
            sharks_at_pos = new_board[r][c]
            sharks_at_pos.sort(key=lambda x: sharks[x][4], reverse=True)
            for loser in sharks_at_pos[1:]:
                del sharks[loser]
```

---

## 💡 자가 진단: "내 코드가 80%만 맞는 이유"
- [ ] 2차원 배열 복사 시 `[row[:] for row in board]` 를 사용했는가?
- [ ] 방향 전환 시 `nr, nc`를 갱신하지 않고 `score`만 올리지는 않았는가?
- [ ] 시작 지점 루프 `N*N*4` 가 정확히 설정되었는가?

---
**이 문서를 백지에 그대로 타이핑할 수 있을 때까지 반복하세요.**
