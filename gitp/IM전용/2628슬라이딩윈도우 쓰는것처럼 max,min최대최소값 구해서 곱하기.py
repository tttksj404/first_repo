import sys

# 입력 받기
c, r = map(int, sys.stdin.readline().split())
n = int(input())

# 시작점(0)과 끝점(r 또는 c)을 미리 포함시킵니다.
garo = [0, r]
sero = [0, c]

for _ in range(n):
    type, pos = map(int, sys.stdin.readline().split())
    if type == 0:  # 가로 절취선 (r을 나눔)
        garo.append(pos)
    else:          # 세로 절취선 (c를 나눔)
        sero.append(pos)

# 1. 정렬하기
garo.sort()
sero.sort()

# 2. 가로 조각들 중 최대 길이 구하기
max_h = 0
for i in range(len(garo) - 1):
    diff = garo[i+1] - garo[i]
    if diff > max_h:
        max_h = diff

# 3. 세로 조각들 중 최대 길이 구하기
max_w = 0
for i in range(len(sero) - 1):
    diff = sero[i+1] - sero[i]
    if diff > max_w:
        max_w = diff

# 4. 결과 출력
print(max_h * max_w)
