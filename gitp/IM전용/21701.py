T= int(input())
for tc in range(1,T+1):
    N,M = map(int, input().split())
    answer_sheet = list(map(int, input().split()))
    student_sheet = [list(map(int,input().split())) for _ in range(N)]
    #현재 인덱스를 시작점으로 정하고, 맞는지 확인 거기서 부터 뒤에 인덱스 맞추면 +1씩 더하는 수에 가점주기
    #만약 틀리면 지금까지 가점 추가해주는거 0으로 초기화 그다음 인덱스 찾기 
    #student_sheet말고 따로 각 학생들의 점수를 저장해놓는 리스트 만들어놓기 [0]으로 이뤄졌고 여기 각행값 sum해버리면 각학생들의 값 나옴
    #최대값 찾고, 최솟값 찾아서 서로 빼주기 이건 그냥 sum해버린 값 따로 리스트에 담아놓고 max,min으로 찾아서 구하기
    scores = []
    plus=0
    storage=0

    for i in range(N):
        for j in range(M):
            if answer_sheet[j]==student_sheet[i][j]:
                plus+=1
                storage+=plus
            else:
                plus=0

        scores.append(storage)
        storage=0
        plus=0
    


    ans = max(scores)-min(scores)
    print(f'#{tc} {ans}')

