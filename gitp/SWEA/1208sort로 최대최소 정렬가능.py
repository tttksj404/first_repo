#처음 테스트 케이스는 10개 이건 for 10개로 돌리기 
#덤프 횟수 = 이동 횟수 = (최대값-1 최솟값+1/ 최대값, 최솟값 재정의)의 반복문 돌릴횟수 
#처음 입력받는 상자들의 높이들 리스트해서 인덱스로 서치 

for a in range(1,11):


    dump = int(input())
    each_box = list(map(int, input().split()))
    for _ in range(dump):
        each_box.sort()
        each_box[-1] -=1 #인덱스 슬라이싱으로 맨 뒤에 인덱스 불러옴 
        each_box[0]+=1
    each_box.sort() #여기서 한번더 정렬해줘야 -1,+1된 값의 제대로된 최소 최대값 알 수 있으므로 다시 정렬해주는거 for 들어가서 원래 초기화 해줬으니        
    answer = each_box[-1] - each_box[0]
    print(f'#{a} {answer}')



'''
아니면 min_value = min(each_box), max_value = max(each_box)로 잡고 
each_box.index(min_value) , each_box.index(max_value)인 상태에서 
해당되는 최소, 최대 인덱스 하나의 값만 가져와서 거기다가 +1 , -1해서 해결해주기

일반적으로 min, max함수만 이용해서 풀면 min인 모든값, max인 모든값이 변경됨 
그렇기에 하나만 지정해서 변경시켜주는게 필수가됨 

'''