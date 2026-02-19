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
    #sample의 손가락은 계속 전진하고, 내가 찾아야할 passcode숫자와 일치할 때만 passcode 손가락을 옆으로 한칸
    # 그래서 idx를 2개 사용한거 = 투 포인터 
    #리스트 슬라이싱은 매번 리스트 훑어야 해서 시간초과 
    #리스트를 한번만 훑어서 끝낸다는게 핵심이여서 투포인터를 사용한 것 
    p_idx = 0
    for s_idx in range(N):
        if sample[s_idx]==passcode[p_idx]:
            p_idx+=1
        if p_idx == K: #특히 여기서 찾으면 끝내서 효율적 passcode를 모두 찾았다면 성공 +종료 
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

'''

# [1] 테스트 케이스의 개수를 입력받습니다.
T = int(input())

# [2] 각 테스트 케이스마다 로직을 수행합니다.
for c in range(T):
    
    # M: Sample(전체 긴 수열)의 길이
    # N: Passcode(우리가 찾아야 하는 암호)의 길이
    M, N = map(int, input().split())
    
    # 전체 숫자 리스트 (여기서 암호를 찾아야 함)
    sample = list(map(int, input().split()))
    
    # 찾아야 하는 목표 암호 리스트
    passcode = list(map(int, input().split()))
    
    # [핵심 변수] start: "지금 passcode의 몇 번째 숫자를 찾고 있는지"를 나타내는 포인터(인덱스)
    # 처음에는 0번 인덱스(첫 번째 암호 숫자)부터 찾아야 하므로 0으로 시작합니다.
    start = 0
    
    # [3] Sample 리스트를 처음부터 끝까지 '한 번만' 쭉 훑습니다. (순차 탐색)
    # i는 현재 검사하고 있는 Sample의 숫자입니다.
    for i in sample:
        
        # [4] ★ 중요: 조기 종료 및 에러 방지 (Safety Guard) ★
        # 만약 start가 N이 되었다면, 0번부터 N-1번까지 모든 암호를 이미 다 찾았다는 뜻입니다.
        # 더 이상 검사할 필요가 없으므로 반복문을 탈출(break)합니다.
        # (이 코드가 없으면, 다 찾은 뒤에도 아래 passcode[start]를 실행하다가
        #  리스트 범위를 벗어나는 'IndexError'가 발생할 수 있습니다!)
        if start == N:
            break
            
        # [5] 타겟 확인 로직
        # 현재 Sample의 숫자(i)가 내가 지금 애타게 찾고 있는 암호 숫자(passcode[start])와 같은가?
        if i == passcode[start]:
            # 같다면, 찾았으니까 다음 암호 숫자를 찾기 위해 포인터를 1 증가시킵니다.
            # (이제 다음 루프부터는 그다음 암호를 찾게 됩니다)
            start += 1
            
    # [6] 결과 출력 로직
    # 반복문이 끝난 뒤, 우리가 찾은 암호의 개수(start)가 목표 개수(N)와 같은지 확인합니다.
    if start == N:
        # 끝까지 다 찾았으면 성공(1)
        print(f'#{c+1} 1')
    else:
        # Sample을 다 뒤졌는데도 start가 N까지 못 갔다면, 중간에 끊긴 것이므로 실패(0)
        print(f'#{c+1} 0')
'''