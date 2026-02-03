T = int(input())
for w in range(1,T+1):
    N = int(input())
    a = 0
    b= 0 
    c= 0
    d= 0
    e= 0
    answer = []
    while N%2 ==0: #N을 2로 나눈 나머지가 0일때 루프시작 아니면 break
        if N%2 ==0:
            a+=1
            N//=2
    answer.append(a)
    while N%3 ==0:
        if N%3 ==0:
            b+=1
            N//=3
    answer.append(b)
    while N%5 ==0:
        if N%5 ==0:
            c+=1
            N//=5
    answer.append(c)
    while N%7 ==0:
        if N%7 ==0:
            d+=1
            N//=7
    answer.append(d)
    while N%11 ==0:
        if N%11 ==0:
            e+=1
            N//=11
    answer.append(e)
    
    print(f'#{w}', *answer)
     


'''
아니면 그냥 2,3,5,7,11을 리스트에 넣어두고 for 로 하나씩 빼서 그걸 while N% 로 돌려주기 계속반복 




T = int(input())
for w in range(1, T + 1):
    N = int(input())
    
    # 각 소인수의 지수(a, b, c, d, e)를 저장할 변수들
    divs = [2, 3, 5, 7, 11]
    results = []

    for d in divs:
        count = 0
        while N% d==0:
            count +=1
            N//=d
        results.append(count)
    print(f'#{w}', *results)
'''