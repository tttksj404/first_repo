T = input().strip() #메모리 스택 관리 하려면 list(map(int, input().split()))자제하기 
if T:
    T = int(T)
for w in range(1,T+1):
    N = int(input()) #numbers의 len값 
    numbers = input().strip()  #list로 받으면 어떻게 받든 전부 나눠짐 split안써도 split은 이미 나눠진것에 대해서 
    answer_count = [0]*10
    for i in numbers:
        answer_count[int(i)]+=1 
       
        
    number = max(answer_count)
    idx = 0

   

# 9부터 0까지 거꾸로 순회 안해주면 index 함수로 풀이시 -> 가장 작은 값을 불러오게됨 앞에서 부터 탐색
    for i in range(9, -1, -1): #뒤로 뒤집어서 보면서 가장 큰 인덱스 걸리게 해줘야함 
        if answer_count[i] == number:
            idx = i
            break  # 가장 큰 인덱스를 찾았으니 바로 탈출
    print(f'{w} {idx} {number}')
    



