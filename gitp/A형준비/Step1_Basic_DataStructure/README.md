# Step 1: 기초 & 자료구조 마스터 가이드

이 단계의 목표는 파이썬의 기본 자료구조를 '알고리즘 문제 해결'에 맞게 효율적으로 사용하는 것입니다.

### 1. `set`을 써야 할 때 (vs `list`)

- **상황**: 어떤 항목이 **'존재하는지 아닌지'** 빠르게 확인해야 할 때.
- **예시**: 1920번 (수 찾기)
- **이유**: `list`에서 `in` 연산은 O(N)이지만, `set`은 O(1)입니다. 데이터가 10만 개라면 속도 차이는 수백만 배에 달합니다.

```python
# Bad (느림)
data = [1, 2, 3, 4, 5]
if 5 in data: # 최악의 경우 5번 비교
    ...

# Good (빠름)
data = {1, 2, 3, 4, 5}
if 5 in data: # 딱 1번의 연산으로 끝
    ...
```

### 2. `heapq`로 우선순위 큐 구현하기

- **상황**: 계속해서 '가장 작은 값' 또는 '가장 큰 값'을 뽑아야 할 때.
- **예시**: 1715번 (카드 정렬하기), 11279번 (최대 힙)
- **핵심 공식**:
  - **최소 힙**: `heapq.heappush(heap, item)` -> `heapq.heappop(heap)`
  - **최대 힙**: `heapq.heappush(heap, -item)` -> `-heapq.heappop(heap)`
  - **복합 기준**: `heapq.heappush(heap, (기준1, 기준2, 값))` (예: 11286번 절댓값 힙)

### 3. 입력 최적화

- **상황**: 입력 데이터가 10만 개 이상일 때.
- **공식**: `input = sys.stdin.readline` 을 코드 상단에 추가하면 `input()`이 훨씬 빨라집니다.
- **주의**: `readline`은 끝에 개행문자(`
`)를 포함하므로, 문자열을 받을 땐 `.strip()`을 함께 써야 합니다.

```python
import sys
input = sys.stdin.readline

# 숫자 한 줄 입력
nums = list(map(int, input().split()))

# 문자열 한 줄 입력
text = input().strip()
```
