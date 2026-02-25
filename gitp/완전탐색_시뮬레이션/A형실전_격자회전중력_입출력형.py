# 자주 틀리는 포인트
# 1) 회전 후 행/열 크기 바뀌는지(직사각형) 확인
# 2) 중력은 아래에서 위로 순회 + write 포인터 방식이 안전
# 3) 벽(-1) 만나면 write를 벽 위 칸으로 갱신해야 함
import sys

# 실전형 연습: 격자 1회 회전 + 중력
# 입력
# N M
# 이후 N줄 (정수, -1 벽 / 0 빈칸 / 양수 블록)

input = sys.stdin.readline
N, M = map(int, input().split())
board = [list(map(int, input().split())) for _ in range(N)]


def rotate_90(mat):
    return [list(row) for row in zip(*mat[::-1])]


def gravity(mat):
    n = len(mat)
    m = len(mat[0])
    for c in range(m):
        write = n - 1
        for r in range(n - 1, -1, -1):
            if mat[r][c] == -1:
                write = r - 1
            elif mat[r][c] > 0:
                v = mat[r][c]
                mat[r][c] = 0
                mat[write][c] = v
                write -= 1


board = rotate_90(board)
gravity(board)

for row in board:
    print(*row)

