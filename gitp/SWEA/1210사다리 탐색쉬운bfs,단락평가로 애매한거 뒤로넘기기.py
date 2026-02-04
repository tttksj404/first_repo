'''
일단 열고정 j 먼저 나오고 그다음 i즉 행을 for 돌려서 행이 점차 내려가는데 한번 내려갈때 마다 [i][j]에서 행고정 j즉 열값만 [i][j-1] , [i][j+1]가 
1이 되면 1되는 쪽으로 이동하도록 하면됨 즉 바꾼 상태에서 다시 i 만 늘어나게됨 그리고 이동해서 다시 똑같이 반복 우선순위는 [j-1]이나 [j+1]로 가는걸 우선으로 하기 



def down(firstx, firsty): #x,y는 스타트 좌표
    for now_yidx in range(100-now_yidx+1): #열을 고정해야 아래로 내려감 
        for now_xidx in range(100-now_xidx+1):

            if locations[now_xidx][now_yidx] == 1:
                if locations[now_xidx][now_yidx+1] == 1:
                    
                    now_yidx +=1
                if locations[now_xidx][now_yidx-1] == 1:
    
                    now_yidx -=1
                if locations[now_xidx+1][now_yidx] == 1:
                    now_xidx +=1
        if locations[now_xidx][now_yidx]  == 2:
            return firstx
'''






'''
for t in range(1,11):
    a = int(input())
    locations = [list(map(int, input().split())) for _ in range(100)]
    
    current_x = 0
    current_y = 99
    for x in range(100):
        if locations[99][x] == 2:
            current_x = x
            break
    
    while current_y >0: #여긴 항상 위로 올라가니까 >0 경우를 결정 해준 상태임 
        if current_x >0 and locations[current_y][current_x-1] == 1:#좌측으로 올라갈때 x-1   #항상 x가 0일때 x-1이고 x+1인 이런 값들이 -1이나 음수가 되어서 범위 벗어나는 것 주의 
            #여기서 단락평가로 and 써서 이미 current_x = 0일때 false 뜨기에 상관 x 그래서 뒤의 조건은 상관없게 된다 
            while current_x >0 and locations[current_y][current_x-1] == 1:
                current_x-=1 
            current_y -=1 #가로 이동 끝나서 위로 이동시키는거 구조적으로 사다리타기가 위로 이동할 부분이 없을 수 없기에 그냥 위로 자동이동됨 이부분은 로직상 필수적
         
        elif current_x <99 and locations[current_y][current_x+1] ==1: #우측으로 올라갈때  x+1
            while current_x <99 and locations[current_y][current_x+1] ==1:
                current_x+=1
            current_y -=1 #이것도 가로 이동 끝나서 위로 이동시킴 

        else: #그냥 위로만 직진으로 올라갈때
            current_y -=1

    print(f'#{t} {current_x}')
    
    

'''
#이거 이렇게는 못푼다. 애초에 전 범위를 훑는게 아닌 이동이 목적이기 때문 
'''

T = int(input())
for w in range(1,T+1):
    ladder = [list(map(int,input().split())) for _ in range(100)]
    #상,좌,우
    dr = [-1,0,0] #행
    dc = [0,-1,1] #열

    #현재 좌표
    r,c = 99,0
    best_r, best_c = 0,0
    #2즉 끝점이 있는 좌표값 구하기
    for a in range(100):
        if ladder[r][a] == 2:
            c = a
        break

    #계속 올라가기 만약 좌우가 없다면 
    for a in range(r,-1,-1):
        for b in range(c,-1,-1):
    #탐색범위
            for i in range(3):
                nr = r+dr[i]
                nc = c+dc[i]
            #만약 좌가 있다면 좌로
            #만약 우가 있다면 우로 이동하기 
            #아니면 위로
            while EOFError:
                if ladder[nr][nc] ==1:
                    best_r = nr
                    best_c = nc
            
    print(f'#{w} {best_c}')

'''  

    






    

                


