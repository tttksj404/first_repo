'''
()로 이뤄져 있는 레이저를 찾고, 그걸 제외한 나머지 괄호의 위치 탐색 
애초에 "(" 다음에 ")"있는지 확인 ")" 전에 "(" 있는지 확인 있으면 그건 레이저
레이저 () 시점으로 부터 "(" 이전에 여전히 "("를 가지는지 확인 ")" 이후에 ")" 가지는지도
    레이저 시점으로 부터 ")" 이후에 "(" 나오면 그건 다른 레이저 혹은 막대기
                    "(" 이전에 ")" 나와도 그건 다른 레이저 혹은 막대기
레이저를 제외한 막대기 시점에서 


그냥 레이저 바로 옆에서 레이저 앞부분 "(" 이전에 "(" 나오면 막대기이고, 레이저 제외한 처음 만나는 ")"까지 구한다음 안에 레이저 몇개 있는지 판단 하고 
레이저 갯수+1 만큼 막대기 수
그 범위의 막대기 "("  ")" 이거 없애주기 
레이저 근처의 막대기 부터 탐색후에 전부 없애주기 이후 
똑같은 매커니즘으로 막대기 "(" 찾고 레이저 () 제외하고, 처음나오는 ")" 까지의 레이저 개수 +1 만큼 막대기 나눠지는 수 
똑같이 그 범위의 막대기 "(" ")" 없애주기 
레이저 제외 막대기 전부 없어질 때 까지 반복 




'''
'''
T = int(input())
for w in range(1, T+1):
    stick = list(input())
    laser_idx = []
    stick_count = 0
    for idx in range(len(stick)-1):
        if stick[idx] == "(" and stick[idx+1] ==")":
            laser_idx.append(idx) #레이저 인덱스의 시작점들 
    while True:
        try:
            for search in laser_idx: #레이저들의 초반 시작점 인덱스인데 맨처음 제외한 레이저들의 초반인덱스 
                stick_idxs = 0 #막대기 시작점과 끝점 인덱스
                stick_idxe = 0
                if search ==0:
                    pass
                else:
                    if stick[search-1]=="(": #search-1 인덱스 부터 쭉 훑어서 레이저를 제외한 ")" 찾기
                        count = 0
                        stick_idxs= search-1
                        for a in range(search,len(stick)):
                            if stick[a] == "(" and stick[a+1] ==")":
                                count+=1 #레이저의 개수
                            if stick[a] ==")":
                                stick_idxe=a
                                stick_count= count+1 #한 구간의 레이저로 인한 막대기 개수 구함  
                                stick[stick_idxs]=0 #막대구간 제외하기 
                                stick[stick_idxe]=0
        except:
            print(f'#{w} {stick_count}')
            break
        
'''

             



T = int(input())
for w in range(1, T+1):
    stick = input().strip() 
    pieces = 0 #막대기 조각들  
    stick_count = 0 #중첩된 막대기 갯수 #중첩 즉 스택을 보기 
    for idx in range(len(stick)):
        if stick[idx] == "(":
            stick_count+=1
        else: #"(" 가 아닌 ")"로 시작하는 경우
            stick_count-=1 
            if stick[idx-1] == "(": # 이 경우는 레이저임 그래서 막대기 갯수라고 했던 거에서 -1
                pieces += stick_count #레이저 발견했으므로 왼쪽의 조각을 추가해주는거 
            else: #stick[idx-1] 이 ")" 인 경우 )) 이니까 이건 끝이라는 소리고 더 이상 중첩되지 않는다는 거라서 그래서 중첩에서 -1 해주는거고, 
                   # 마지막 끝나는데 레이저로 쪼개져서 한조각 더 추가해주는 메커니즘 
                pieces +=1
    print(f'#{w} {pieces}')









