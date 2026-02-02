
count = 0 
while True:
    try:
        
        count+=1
    #일단 내가 고른 하나의 빌딩 정하고, 그 빌딩의 인덱스 +2+1-1-2의 인접 빌딩이 리스트로 있을텐데 그게 내가 고른 빌딩보다 작을때만 정답 빌딩의 개수가 +1됨  
        total_buildings = int(input())
        buildings = list(map(int, input().split()))
# 여러개의 테스트 케이스가 주어지므로, 각각을 처리합니다.
        longest_building_legth = 0
        answer = 0
        for each in range(2,total_buildings-2):  #앞에 2개 뒤에 2개는 0이므로 인덱스 에러 방지를 위해서 건너뛰어서 2부터 그리고 -2해서 뒤에 2개 제외하고 시작해주기
            if buildings[each] > buildings[each+1] and buildings[each] > buildings[each+2] and buildings[each] > buildings[each-1] and buildings[each] > buildings[each-2]:
                longest_building_legth=buildings[each] 
                storage = [buildings[each+1],buildings[each+2],buildings[each-1],buildings[each-2]]
                answer+=longest_building_legth-max(storage) #여기서 두번째 큰 빌딩과 내가 고른 가장 큰 지금 빌딩과의 높이차는 조망권 확보 세대임
                longest_building_legth=0

        print(f'#{count} {answer}')
    except EOFError:
        break
