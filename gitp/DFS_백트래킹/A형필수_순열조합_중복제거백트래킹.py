'''
A형에서 진짜 자주 나오는 형태
1) 순열(중복 없이 뽑기)
2) 조합(오름차순 인덱스 기반으로 뽑기)

핵심
- visited 처리
- depth(선택한 개수) 기준 종료
- 조합은 start 인덱스 넘겨서 중복 방지
'''

# 예시 데이터
nums = [1, 2, 3, 4]
M = 2

# -----------------------------
# 1) 순열
perm_result = []
visited = [False] * len(nums)
path = []

def make_perm(depth):
    if depth == M:
        perm_result.append(path[:])
        return

    for i in range(len(nums)):
        if visited[i]:
            continue
        visited[i] = True
        path.append(nums[i])

        make_perm(depth + 1)

        path.pop()
        visited[i] = False

# -----------------------------
# 2) 조합
comb_result = []
path2 = []

def make_comb(start, depth):
    if depth == M:
        comb_result.append(path2[:])
        return

    for i in range(start, len(nums)):
        path2.append(nums[i])

        make_comb(i + 1, depth + 1)

        path2.pop()


make_perm(0)
make_comb(0, 0)

print('[순열 결과]')
for p in perm_result:
    print(p)

print('[조합 결과]')
for c in comb_result:
    print(c)
