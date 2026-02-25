'''
N은 떨어뜨릴 구슬의 개수라서 초반 벽돌에 적힌 숫자 1인 벽돌이 시작점이라고 하기 -> 어짜피 다 해서 벽돌 개수 가장 적어지는거 고르면 되니까 초반 조건 상관x
벽돌에 적힌 숫자 만큼 폭발의 범위 결정 1 은 자기만 터짐 2부터 자기+상하좌우임 상하좌우로 ( 벽돌에 적힌 숫자 - 1 ) 칸 만큼 같이 제거
터진 곳은 터진 곳에 적힌 숫자 확인하고, 숫자에 따라서 상하좌우인지 아니면 자기만인지 조건으로 정해주고 -> 0으로 바꾸기 
그렇게 N번의 반복문 전부 돌고 남은 벽돌 1의 개수 세고, 가장 적은 개수가 되는게 답


'''
T = int(input())
for z in range(1,T+1):
    N , W, H = map(int, input().split()) #N은 구슬 개수 / W는 열 넓이 / H는 행 높이
    brick_map = [list(map(int, input().split())) for _ in range(W)]
    bomb_i , bomb_j =0,0
    di = [-1,1,0,0] #상하좌우
    dj = [0,0,-1,1]
    min_brick = 999
    #시작점 찾기 
    for a in range(N):
        for b in range(W):
            for q in range(N):
                for i in range(H):
                    for j in range(W):
                        if brick_map[i][j] >=1:
                            bomb_i,bomb_j = i,j #구슬 시작점
                            for p in range(4):
                                nr = i+di[p]*(brick_map[i][j]-1) #벽돌에 적힌 수 만큼 범위 확장 
                                nc = j+dj[p]*(brick_map[i][j]-1)
                                if nr<0 or nr>H-1 or nc<0 or nc>W-1:
                                    continue
                                elif brick_map[nr][nc] >=2:
                                    pass
                                elif brick_map[nr][nc] ==1:
                                    brick_map[i][j]=0
                                    brick_map[nr][nc]=0
            brick_count =brick_map.count(1)
            if min_brick> brick_count:
                min_brick=brick_count
    print(f'{z} {min_brick}')





