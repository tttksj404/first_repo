
'''
T = int(input())
for a in range(1,T+1):
    for _ in range(9):
        numbers = list(map(str, input().split()))
        ilist=[]
        jlist=[]
        
    for j in range(9):
        for i in range(9):
            ilist.append(numbers[j][i])
        if len(set(ilist)) ==9: #set는 true false x 그냥 수랑 비교하면됨 
            print(f'#{a} 1')
            break
        
        
    for i in range(9):
        for j in range(9):
            jlist.append(numbers[j][i])
        if len(set(jlist)) ==9:
            print(f'#{a} 1')
            break


    for r in range(0,9,3):
        for c in range(0,9,3):
            box = set()
            for i in range(3):
                for j in range(3):
                    box.add(numbers[r+i][c+j])
            
            if len(box) != 9:
                print(f'#{a} 1')
                break
            else:
                print(f'#{a} 0')
'''


T = int(input())

for a in range(1, T + 1):
    # [1] 9x9 전체 데이터를 2차원 리스트로 받기
    sudoku = [list(map(int, input().split())) for _ in range(9)]
    
    ans = 1 # 기본적으로 올바르다고 가정

    # [2] 가로(행) 검사
    for i in range(9):
        if len(set(sudoku[i])) != 9:
            ans = 0
            break

    # [3] 세로(열) 검사 (가로가 통과되었을 때만 수행)
    if ans == 1:
        for i in range(9):
            col_list = [sudoku[j][i] for j in range(9)] # i번째 열의 숫자들을 모음
            if len(set(col_list)) != 9:
                ans = 0
                break

    # [4] 3x3 박스 검사 (위의 검사들이 통과되었을 때만 수행)
    if ans == 1:
        for r in range(0, 9, 3): # 0, 3, 6
            for c in range(0, 9, 3): # 0, 3, 6
                box = []
                for i in range(3):
                    for j in range(3):
                        box.append(sudoku[r+i][c+j])
                if len(set(box)) != 9:
                    ans = 0
                    break
            if ans == 0: break

    print(f'#{a} {ans}')

    


