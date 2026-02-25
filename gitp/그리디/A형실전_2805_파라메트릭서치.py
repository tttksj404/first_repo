# 자주 틀리는 포인트
# 1) 가능한 경우(lo=mid+1), 불가능한 경우(hi=mid-1) 방향 반대로 쓰지 않기
# 2) 정답은 조건 만족 시마다 ans=mid로 갱신
# 3) 경계값 lo, hi를 문제 정의(최소/최대 가능 값)로 정확히 설정
import sys

# BOJ 2805 나무 자르기
# 파라메트릭 서치

input = sys.stdin.readline
N, M = map(int, input().split())
trees = list(map(int, input().split()))


def possible(h):
    total = 0
    for x in trees:
        if x > h:
            total += x - h
    return total >= M


lo, hi = 0, max(trees)
ans = 0

while lo <= hi:
    mid = (lo + hi) // 2
    if possible(mid):
        ans = mid
        lo = mid + 1
    else:
        hi = mid - 1

print(ans)

