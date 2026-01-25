N = 9
data_1 = '123456789'
arr_1 = []
# 아래에 코드를 작성하시오.
for ind in range(N):  #range(N)은 len(data_1)과 동일 문자열 길이
    a = data_1[ind] #문자열 길이로 index값 나열해주고 그 index 값별로 list에 append
    arr_1.append(a)
print(arr_1)

M = 15
data_2 = '1 2 3 4 5 6 7 8 9 10 11 12 13 14 15'
# 아래에 코드를 작성하시오.

arr_2 = []
b = data_2.split() #먼저 split()으로 공백 기준 문자들 구분해서 리스트에다가 넣음 
#그게 바로 split() 이건 바로 ()안에 기준으로 리스트에다가 넣는다는 것
for ind2 in range(M): 
    if int(b[ind2]) % 2 ==0: #리스트 안에 들어간 값 다시 index로 구분해서 각 개별 값들이 홀수인지 짝수인지 판별
        pass
    else:
        print(b[ind2]) #홀수면 그 인덱스 값 계속 출력 돌리는 것 
    
    