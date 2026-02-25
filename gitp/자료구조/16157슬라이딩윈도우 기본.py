N, X = map(int, input().split())
numbers = list(map(int, input().split()))

window = sum(numbers[:X]) #윈도우 안에 값 다 더해주고
day = 1
max_sum = window #맥스값 갱신 
for a in range(N-X):
    window = window -numbers[a] +numbers[a+X] #초반 값 빼주고, 뒤에값 더해주고 
    if window >max_sum: #지금 윈도우가 최고값이라면
        max_sum = window #최고값을 윈도우로 갱신
        day =1 #당연히 최고값 갱신이라 기간 1개로 초기화
    elif window == max_sum:
        day+=1 #최고 값이랑 같으면 당연히 기간 1개에서 2개되기에 1개씩 추가
if max_sum ==0:
    print("SAD")
else:
    print(max_sum)
    print(day)
