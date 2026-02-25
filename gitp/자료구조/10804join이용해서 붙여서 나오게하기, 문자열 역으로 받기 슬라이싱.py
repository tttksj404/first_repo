T = int(input())
for w in range(1,T+1):
    word = input().strip()
    dicts = {"b":"d","d":"b","p":"q","q":"p"}
    ans = []
    for a in word:
        ans.append(dicts[a])
    real_ans = ans[::-1] #문자열 역으로 받는거 
    print(f'#{w}', "".join(real_ans)) #*로 리스트 하면 문자 하나하나 공백으로 뛰어쓰기 된 상태로 등장함
    #하지만 ""join은 다 붙어서 나오게됨 

'''
T_input = input().strip()

# 테스트 케이스 개수가 정상적으로 입력된 경우만 시작
if T_input:
    T = int(T_input)
    
    for w in range(1, T + 1):
        # 1. 단어 입력 받기 (빈 줄이 오면 실제 단어가 나올 때까지 다시 읽기)
        word = input().strip()
        while not word:
            word = input().strip()
            
        # 2. 거울 변환 딕셔너리
        mirror_map = {"b": "d", "d": "b", "p": "q", "q": "p"}
        
        # 3. 변환된 글자들을 담을 리스트
        ans = []
        for char in word:
            ans.append(mirror_map[char])
            
        # 4. 순서 뒤집기 및 합쳐서 출력
        # f-string 안에 "".join()을 넣으면 출력 형식이 더 깔끔해집니다.
        print(f'#{w} {"".join(ans[::-1])}')

'''