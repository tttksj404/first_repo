T = int(input())
for w in range(1,T+1):
    k = int(input())
    pattern = input()
    Alist = []
    for idx in range(len(pattern)): #애초에 반복을 인덱스 값으로 해서 
        if pattern[idx] == "A": #인덱스 값으로 나온 문자가 만족시
            Alist.append(idx) #해당 A의 인덱스를 저장해서 길이를 사용하기 쉽게 만듦 
    if len(Alist)<k :
        print(f'{w} 0')
    else:
        max_Alen = 0
        for a in range(len(Alist)-k+1): #K번째 A의 위치0부터 세서 마지막 -1 해주는 것 
            Alen = Alist[a+k-1]-Alist[a] #마지막A 부터 첫A까지의 길이 
            if Alen >= max_Alen:
                max_Alen = Alen
        print(f'{w} {max_Alen}')



    