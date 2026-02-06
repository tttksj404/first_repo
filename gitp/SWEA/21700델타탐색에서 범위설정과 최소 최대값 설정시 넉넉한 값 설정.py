'''
Y,X로부터 가장 먼 MAX(hy,hx)를 구해서 D**2구하기 Y,X는 중계기 위치
D**2 = (hy - y)**2 + (hx - x)**2

D**2 구하고 R은 1~15 까지 돌려서
D**2<=R**2 이거 만족하는 R값중 최소R값 구하기
'''
T = int(input())
for w in range(1,T+1):
    N = int(input())
    square = [list(map(int,input().split())) for _ in range(N)]
    central_r,central_c = 0,0 #시작값
    for i in range(N):
        for j in range(N):
            if square[i][j] == 2:
                central_r,central_c = i,j
    #이건 중계기로 부터 가장 먼 집 찾는거
    max_hr,max_hc = central_r,central_c
    for a in range(N):
        for b in range(N):
            if square[a][b]==1:
                distance = (a-central_r)**2+(b-central_c)**2
                distancetwo = (max_hr-central_r)**2+(max_hc-central_c)**2
                if distance > distancetwo:
                    max_hr=a
                    max_hc=b

    max_D = (max_hr-central_r)**2+(max_hc-central_c)**2
    min_R = 999
    for R in range(1,N+10): #범위는 넉넉하게 N보다 R즉 반지름이 더 넓을 수 있어서 중요! 
        if max_D<=R**2:
            if R<min_R:
                min_R=R
    print(f'#{w} {min_R}')