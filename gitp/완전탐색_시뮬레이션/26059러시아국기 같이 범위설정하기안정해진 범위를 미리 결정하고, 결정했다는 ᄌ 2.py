#첫째 줄 N을 통해서 lo,hi사이 값으로 N채울 수 있는거 만들면된다 최대한 비슷한 수로 
# 3가지 공간에 숫자 배치
#  1. 0<  <k1 / 2. k1<  <k2 / 3. k2<  <max값
#  1 3 4 5 5 -> 중복되어 있는 값 이전까지 기준 혹은 중복된 값 이후부터 기준 
# 1 1 1 2 5 -> 1은 중복되니까 전부 묶고, 이후 부터 기준됨  나머지 기준은 상관없음

#어디가 중복되는지 값 sort하고 그런다음 하나씩 뽑아서 이전 인덱스가 지금 인덱스와 같으면 딕셔너리에 해당 숫자 갯수 1에서 +1더해주기
#그럼 그 딕셔너리의 해당 숫자 벨류값 -1이 해당 중복되는 숫자의 마지막 인덱스

T = int(input())
for tc in range(1,T+1):
    N,lo,hi = map(int,input().split()) #N은 과일 수 num의 총 길이 
    num = list(map(int,input().split()))
    num.sort() #1 3 4 5 5 
    a=sorted(list(set(num))) #1 3 4 5  #set은 순서 뒤죽박죽 되니까 다시 정렬해주고 리스트로 인덱스 가져오게 해줘야함
    ans = 999 #최솟값
    found = False
    #k1, k2의 값을 확정해주고 그것에 대해서 범위설정되므로 k1,k2를 범위로 잡아줄 필요는 없다 
    for i in range(len(a)):
        for j in range(i+1, len(a)):
            k1 = a[i]
            k2 = a[j]

            economy = 0
            standard = 0
            premium = 0

            for each in num:
                if each<k1:
                    economy+=1
                elif k1<=each<k2:
                    standard+=1
                elif k2<=each:
                    premium+=1

            if lo<=economy<=hi and lo<=standard<=hi and lo<=premium<=hi:
                fruit = max(economy,standard,premium)-min(economy,standard,premium)
                if fruit < ans:
                    ans = fruit
                    found = True
    if found==True:
        print(f'#{tc} {ans}')
    else:
        print(f'#{tc} -1')


    
    
    


    

    





