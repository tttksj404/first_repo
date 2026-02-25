'''
파라메트릭 서치(결정 문제 + 이분 탐색)
- 정답을 직접 찾지 않고
- "x가 가능한가?"를 기준으로 범위를 줄여감

대표: 랜선 자르기, 공유기 설치, 예산 상한
'''

# 예시: 길이가 주어진 랜선을 잘라서, 최소 K개 이상 만들 수 있는
# "최대 길이"를 구하기

lines = [802, 743, 457, 539]
K = 11


def can_make(length):
    # length 길이로 잘랐을 때 K개 이상 만들 수 있는가?
    if length <= 0:
        return True
    cnt = 0
    for x in lines:
        cnt += x // length
    return cnt >= K


lo, hi = 1, max(lines)
ans = 0

while lo <= hi:
    mid = (lo + hi) // 2

    if can_make(mid):
        ans = mid
        lo = mid + 1
    else:
        hi = mid - 1

print(ans)
