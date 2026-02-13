puzzel = []
for _ in range(9):  #이안에서 만드는게 아님을 생각 이건 그냥 지도 만드는 for 일뿐이다.
    puzzel.append(list(map(int, input().split())))
max_num = -1 #모든 수가 0일 경우를 대비해 -1로 시작 필요 
max_x =0
max_y =0

for r in range(9):
    for c in range(9):
        if puzzel[r][c] >= max_num:
            max_num= puzzel[r][c]
            max_y = r
            max_x = c


print(max_num)
print(max_y+1,"",max_x+1) #문제에서 0번 인덱스도 1행 으로 취급하기때문에 문제에 따른 보정 필요

    



