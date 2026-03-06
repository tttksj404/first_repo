# Step 2: 완전탐색 & 백트래킹 마스터 가이드

이 단계의 목표는 '모든 경우의 수'를 체계적으로 탐색하는 재귀적 사고력을 기르는 것입니다. 삼성 A형의 심장과도 같은 유형입니다.

### 1. 백트래킹의 만능 템플릿 (DFS)

모든 백트래킹 문제는 아래의 구조를 거의 그대로 따릅니다.

```python
def dfs(depth, path):
    # 1. 기저 조건 (언제 멈출 것인가?)
    if depth == N:
        # 정답 처리
        print(path)
        return

    # 2. 유도 파트 (어떤 선택을 할 것인가?)
    for i in range(후보 시작, 후보 끝):
        if is_promising(i): # 이 후보가 유망하다면?
            # 2-1. 선택
            path.append(i)
            # 2-2. 다음 단계로
            dfs(depth + 1, path)
            # 2-3. 선택 취소 (가장 중요!)
            path.pop() 
```

- `path.pop()` (백트래킹)이 핵심입니다. 다음 경우의 수를 위해 현재의 선택을 원상 복구하는 과정입니다.

### 2. 순열 vs 조합

- **순열 (Permutation)**: 순서가 중요. `(1,2)`와 `(2,1)`은 다름.
  - **핵심**: `visited` 배열로 사용 여부를 체크.
  - **예시**: 10974번 (모든 순열)
  ```python
  # for문이 항상 0부터 시작, visited로 중복 방지
  for i in range(N):
      if not visited[i]:
          visited[i] = True
          ...
          visited[i] = False # 백트래킹
  ```

- **조합 (Combination)**: 순서 무관. `(1,2)`와 `(2,1)`은 같음.
  - **핵심**: `start_index`를 인자로 넘겨 이전에 썼던 건 다시 안 보게 함.
  - **예시**: 6603번 (로또), 14889번 (스타트와 링크)
  ```python
  # for문이 start_index부터 시작
  def dfs(depth, start_index):
      ...
      for i in range(start_index, N):
          ...
          dfs(depth + 1, i + 1) # 다음 재귀는 i+1부터
  ```

이 두 가지 구조만 완벽히 외우면 대부분의 백트래킹 문제를 풀 수 있습니다.
