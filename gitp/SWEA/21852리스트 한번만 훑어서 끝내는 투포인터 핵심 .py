'''
passcode에서의 첫번째 값을 sample과 비교해서 찾고 거기서부터 시작 하면됨 그다음 sample의 인덱스부터 찾기 시작해야됨
이걸 passcode를 for로 돌려서 하나씩 꺼내고 sample의 인덱스로 돌려서 나온 값과 비교후 일치하면 그 인덱스 기억
그 인덱스 이후부터 다시  위의 내용 반복해야되니까 while로 전체를 묶어줌
그래서 passcode의 모든 글자 뽑아올때 까지 위의 조건 다 만족하면
print(1)

만약 그 다음 값이 인덱스 이후에 없으면 break
print(0)


T = int(input())
for w in range(1,T+1):
    N, K = map(int, input().split())
    sample = list(map(int, input().split())) #N이 sample의 길이
    passcode = list(map(int, input().split())) #K가 passcode의 길이
    next_idx = 0 #passcode를 여기서 부터 검사 시작하는 인덱스
    check_up = []
    while True:
        for code in passcode:
            for idx in range(N):
                if sample[idx] == code:
                    next_idx = idx+1
                    passcode.remove(code)
                if code not in sample[next_idx::]:
                    print(f'#{w} 0')
                    break

        if passcode is False:
            print(f'#{w} 1')
        for s in passcode:
            for a in range(next_idx,N):
                if sample[a] == s:
                    idx=a+1
                    passcode.remove(s)
                if s not in sample[idx::]:
                    print(f'#{w} 0')
                    break
        if passcode is False:
            print(f'#{w} 1')
'''

T = int(input())
for w in range(1,T+1):
    N, K = map(int, input().split())
    sample = list(map(int, input().split())) #N이 sample의 길이
    passcode = list(map(int, input().split())) #K가 passcode의 길이
    s_idx =0 #sample의 손가락은 계속 전진하고, 내가 찾아야할 passcode숫자와 일치할 때만 passcode 손가락을 옆으로 한칸
    # 그래서 idx를 2개 사용한거 = 투 포인터 
    #리스트 슬라이싱은 매번 리스트 훑어야 해서 시간초과 
    #리스트를 한번만 훑어서 끝낸다는게 핵심이여서 투포인터를 사용한 것 
    p_idx = 0
    for s_idx in range(N):
        if sample[s_idx]==passcode[p_idx]:
            p_idx+=1
        if p_idx == K: #특히 여기서 찾으면 끝내서 효율적 
            break

    if p_idx == K:
        print(f'#{w} 1')
    else:
        print(f'#{w} 0')
'''
t = int(input())
 
for tc in range(1, t+1):
    n, k = map(int, input().split())
    sample = list(map(int, input().split()))
    passcode = list(map(int, input().split()))
 
 
    check = -1 
    answer = 1
 
    for i in passcode:
        try:                        #이런식으로 try except 예외로 처리가능 try에 에러발생하면 except로 가기때문
        
            check = sample.index(i, check+1) #index를 찾는건데 (i라는 문자를 찾는데 리스트[check+1]"부터" 탐색 )
            #여기서 sample에서 인덱스 하나씩 뒤로가서 탐색함 전부 탐색하고도 안나오면 error나와서 except으로 들어가고 0나옴
        except:
            answer = 0
            break
 
    print(f'#{tc}', answer)

'''