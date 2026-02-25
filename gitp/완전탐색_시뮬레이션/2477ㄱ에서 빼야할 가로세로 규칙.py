'''
동서 - 1,2
남북 - 3,4
전체 값중에서 동,서 중 큰거 * 남,북 중에서 큰값 = 전체넓이
동,서 중 가장 작은 값 * 남,북 중에서 가장 작은 값 = 빼야할 넓이
전체넓이-빼야할 넓이 = 구할 넓이
구할넓이*n = 참외갯수


'''
N=int(input())
commands = [list(map(int,input().split())) for _ in range(6)]

east_west =[] #1,2
north_south = [] #3,4
only_command = []
for i in range(6):
    only_command.append(commands[i][1])
    for j in range(2):
        if commands[i][0]==1 or commands[i][0]==2:
            east_west.append(commands[i][1])
        elif commands[i][0]==3 or commands[i][0]==4:
            north_south.append(commands[i][1])
a=only_command.index(max(north_south))
b=only_command.index(max(east_west))
#가장 긴 '세로'에서 3칸 뒤를 찾으면 ->빼야 할 '가로'가 나옵니다.
# 가장 긴 '가로'에서 3칸 뒤를 찾으면 ->빼야 할 '세로'가 나옵니다.
min_north_south = only_command[(a + 3) % 6] #이게 핵심임 빼야할 가로세로의 등장규칙찾기
min_east_west = only_command[(b + 3) % 6]


whole = max(north_south)*max(east_west)
minus = min_north_south*min_east_west
entire = whole-minus
ans= entire*N
print(ans)

