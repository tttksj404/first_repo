'''
여기서 




'''

'''
T = int(input())
for w in range(1,T+1):
    N = int(input()) #노선의 총 개수
    storage = []
    answer_dict = {}
    for n in range(1,N+1): #노선의 수 만큼 반복해서 각 노선의 정류장 파악
        A,B = list(map(int, input().split()))
        for stations in range(A,B+1):
            storage.append(stations)
    P = int(input())
    for a in range(1,P+1):
        answer_dict.update(int(input()))
        answer_dict.get(a, storage.count(a))
        
    print(f'{w} {answer_dict.values()}')
'''




T = int(input())

for w in range(1, T + 1):
    N = int(input())
    
    # 1~5000번 정류장 방문 횟수를 저장할 리스트 (인덱스 0은 버림)
    # count()를 매번 쓰는 것보다 미리 더해두는 게 훨씬 빠름 0부터 시작해서 +1
    bus_stop = [0] * 5001 #애초에 수가 정해져있다면 리스트 미리 생성해주는 것도 방법
    for _ in range(N):
        A,B = map(int, input().split())
        for i in range(A, B+1):
            bus_stop[i] +=1
    P = int(input())
    answer = []

    for _ in range(P):
        cj = int(input())
        answer.append(bus_stop[cj])
    
    print(f'{w}', *answer) #애스터리스크 f 스트링 밖에서 사용 혹은
    #print(f'#{w} {" ".join(map(str, answer))}') 사용 









    #for numbers in set(storage):
        #storage.count(numbers)




