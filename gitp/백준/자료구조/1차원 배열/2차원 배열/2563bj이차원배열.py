paper = [] #이건 전체 종이 범위 
for _ in range(100):   # 세로로 100 잡아주고 
    row = []
    for _ in range(100): #가로를 100잡아서 100번 반복때 마다 가로 0하나씩 넣어주기 
        row.append(0)
    paper.append(row) #여기서 for에서 세로 row 넣으면 각 행별로 row를 넣기때문에 100x100이이뤄짐 


N = int(input())

for _ in range(N):
    x,y = map(int, input().split()) #x,y 좌표로 풀어야겠다 생각후 x,y가 결국 N번 반복된다는 거 판단해서 넘어가기 
    for r in range(x, x+10): #r은 색종이 하나의 x범위 
        for c in range(y, y+10): #c는 색종이 하나의 y범위 
            paper[r][c] =1 #x,y 좌표로 색종이 있는 부분은 전체다 1넣어주기 x,y는 색종이 좌표임 

#이부분은 다시 전체 종이 탐색하면서 색종이 부분 확인해주는 것 
total_area = 0 #total_area를 0넣어서 초기화
for i in range(100): 
    for j in range(100):
        if paper[i][j] ==1: #색종이 부분 1확인되면 1넣어서 확인 / 애초에 중복은 볼 필요가 없었음 어짜피 for로 한번만 탐색하니까 
            total_area+=1
print(total_area)






