'''

1.우측 아래는 r값 은 반드시 아래로 1이상 N전까지 늘어날 수 있음  c값은 0부터 N전까지 늘어날 수 있음
    1-1대신 우측 아래로 드래그 사각형 그릴 수 있음 반드시 for 돌려서 해당 사각형 시작값 과 끝 값이 같음 이게 조건임
    1-2조건 만족시 시작값r,c 좌표 끝값 a,b 좌표 각각 뺀 값 abs(a-r)+1 * abs(b-c)+1 하면 해당 사각형안에 있는 면적 구할 수 있음
    1-3 이걸 만족하면 사각형 면적 담아놓는 리스트 만들고
    1-4 그 리스트에서 max해서 최대면적 구한다음 그 리스트에서 최대면적 몇개 가졌는지 count 하면 끝


'''

T = int(input())
for w in range(1,T+1):
    N = int(input())
    game_map = [list(map(int,input().split())) for _ in range(N)]
    r,c = 0,0
    square_list = []

    #시작값 정의
    for i in range(N):
        for j in range(N):
            r,c=i,j

            #시작값에 대한 끝값 구하기
            for a in range(r,N):
                for b in range(c,N):
                    if game_map[r][c] == game_map[a][b]:
                        how_many = (abs(a-r)+1) * (abs(b-c)+1)
                        square_list.append(how_many)
    pre_ans = max(square_list)
    ans = square_list.count(pre_ans)
    print(f'#{w} {ans}')





