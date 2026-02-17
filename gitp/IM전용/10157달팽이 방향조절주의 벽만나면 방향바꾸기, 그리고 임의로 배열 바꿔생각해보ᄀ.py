'''
그냥 가로랑 세로를 바꿔서 생각하기
0,0이 1,1이라서 여기서 시작해서 오른쪽가면됨
그래서 출력값은 항상 원래 인덱스값에서 +1된 값 행렬모두
'''
r,c = map(int,input().split())#7,6 
target = int(input())
total= [[0]*c for _ in range(r)]
#우,하,좌,상
dr=[0,1,0,-1]
dc=[1,0,-1,0]
s_i, s_j=0,0
dist=0
for num in range(1,r*c+1):
    if r*c<target:
        print(0)
        break
    total[s_i][s_j]=num
    if total[s_i][s_j]==target:
        print(f'{s_i+1} {s_j+1}')
        break
    nr = s_i+dr[dist]
    nc = s_j+dc[dist]
    if 0<=nr<=r-1 and 0<=nc<=c-1 and total[nr][nc]==0:
        pass
    else:
        dist=(dist+1)%4
        nr = s_i+dr[dist]
        nc = s_j+dc[dist]
    s_i,s_j=nr,nc
    if total[s_i][s_j]==target:
        print(f'{s_i+1} {s_j+1}')
        break
    




        



