'''
N*N 격자판 
가로,세로,대각선 
바둑알 하나 찾고 거기서 가로 연속 5개 이상
대각선 왼쪽 아래 / 대각선 오른쪽 아래 5개 이상 
list(zip(*matrix)) 행렬 전치사용
'''
'''
T = int(input())
for tc in range(1,T+1):
    N = int(input())
    matrix = [list(map(int,input())) for _ in range(N)]
    reverse_matrix = list(zip(*matrix)) 
    s_i, s_j = 0,0
    check_count = 0
    flag= False
    #스타트 바둑알 정하기
    for i in range(N):
        if flag==True:
            break
        for j in range(N):
            if matrix[i][j]== "o":
                s_i,s_j = i,j
                #가로
                for idx in range(s_j,s_j+5):
                    if matrix[s_i][idx]=="o":
                        check_count+=1
                if check_count!=5:
                    pass
                else:
                    print(f'#{tc} YES')
                    flag = True
                    break
                check_count=0
                #세로
                for ind in range(s_j,s_j+5):
                    if reverse_matrix[s_j][ind]=="o":
                        check_count+=1
                if check_count!=5:
                    pass
                else:
                    print(f'#{tc} YES')
                    flag = True
                    break
                check_count=0
                #대각선 오른쪽아래
                for z in range(5):
                    s_i+=z
                    s_j+=z
                    if matrix[s_i][s_j]=="o":
                        check_count+=1
                    s_i,s_j = i,j
                if check_count!=5:
                    pass
                else:
                    print(f'#{tc} YES')
                    flag = True
                    break
                #대각선 왼쪽아래
                for z in range(5):
                    s_i+=z
                    s_j-=z
                    if matrix[s_i][s_j]=="o":
                        check_count+=1
                    s_i,s_j = i,j
                if check_count!=5:
                    pass
                else:
                    print(f'#{tc} YES')
                    flag = True
                    break
    print(f'#{tc} NO')
'''

T = int(input())
for tc in range(1,T+1):
    N = int(input())
    matrix = [input() for _ in range(N)]
    #가로 오른쪽/ 세로 아래쪽 / 대각선 왼쪽아래 / 대각선 오른쪽 아래
    dr = [0,1,1,1]
    dc = [1,0,-1,1]
    s_i,s_j=0,0
    flag= False
    for i in range(N):
        if flag ==True:
            break
        for j in range(N):
            if flag == True:
                break
            if matrix[i][j]=="o":
                s_i,s_j=i,j
                #4방향 5번 반복해서 나아갈 수 있는지
                for d in range(4):
                    if flag == True:
                        break
                    count=1
                    for k in range(1,5):
                        nr = s_i+dr[d]*k
                        nc = s_j+dc[d]*k
                        #범위 안벗어나고 돌 이 있으면 카운트 증가
                        if 0<=nr<=N-1 and 0<=nc<=N-1 and matrix[nr][nc]=="o":
                            count+=1
                        #벗어나면 벗어나기
                        else:
                            break
                    if count >=5:
                        print(f'#{tc} YES')
                        flag = True
                        break
    if flag == False:
        print(f'#{tc} NO')
    







                        
                        




    