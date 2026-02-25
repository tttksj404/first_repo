'''
A형 구현 필수 패턴
1) 부분 격자 회전(90도)
2) 중력 적용(아래로 떨어뜨리기)

문제마다 회전 단위와 중력 규칙만 조금씩 바뀜
'''

# -1: 벽, 0: 빈칸, 양수: 블록
board = [
    [1, 0, 2, 0],
    [0, -1, 0, 3],
    [4, 0, 0, 0],
    [0, 5, 0, 6],
]

N = 4


def rotate_90(mat):
    # 시계방향 90도 회전
    return [list(row) for row in zip(*mat[::-1])]


def apply_gravity(mat):
    # 벽(-1) 기준으로 아래로 블록 몰아넣기
    n = len(mat)
    m = len(mat[0])

    for c in range(m):
        write = n - 1
        for r in range(n - 1, -1, -1):
            if mat[r][c] == -1:
                write = r - 1
            elif mat[r][c] > 0:
                val = mat[r][c]
                mat[r][c] = 0
                mat[write][c] = val
                write -= 1


print('[원본]')
for row in board:
    print(row)

board = rotate_90(board)
print('[회전 후]')
for row in board:
    print(row)

apply_gravity(board)
print('[중력 후]')
for row in board:
    print(row)
