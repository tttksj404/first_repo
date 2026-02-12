'''
0이면 1
1이면 0
이건 뒤에 숫자 전부에게 영향을 끼친다 

초반값은 일단 입력값의 1이 등장하는 처음값부터 수정
바꿔서 뒤에 숫자 까지 전부 0->1 또는 1->0으로 바꿔줌
이때 입력값이 목표값이므로 이거랑 같은지 확인후 다르면 
그다음 인덱스에서 다른 값이 있는 인덱스 부터 다시 수정


앞에서 부터 큰거부터 바꾸고 나머지 뒤에건 정해진다는 그리디 문제
'''
'''
T = int(input())
for tc in range(1,T+1):
    target = list(map(int,input().strip()))
    count=0

    default = [0]*len(target) #기본값 
    while target != default:
        for idx in range(len(target)):
            if target[idx] != default[idx]:
                count+=1
                if default[idx]==1:
                    for a in range(idx, len(target)):
                        default[a]=0
                if default[idx]==0:
                    for a in range(idx, len(target)):
                        default[a]=1
                
           
    print(f'#{tc} {count}')
               
        
'''

T = int(input())
for tc in range(1,T+1):
    target = list(map(int,input().strip()))
    count=0
    default = [0]*len(target)
    
    for idx in range(len(target)):
        if target[idx] != default[idx]:
            count+=1
            if default[idx]==1 and target[idx]==0:
                for a in range(idx, len(target)):
                    default[a]=0
            if default[idx]==0 and target[idx]==1:
                for a in range(idx, len(target)):
                    default[a]=1        
            if target == default:
                print(f'#{tc} {count}')
                break
                

    
'''

T = int(input())
for tc in range(1, T + 1):
    target = input().strip()
    count = 0
    # 현재 모든 뒤쪽 비트가 어떤 값으로 덮어씌워져 있는지 '상태'만 저장
    current_state = '0' 

    for bit in target:
        if bit != current_state:
            count += 1
            # 버튼을 눌러서 현재 상태를 목표 비트로 바꿈
            # 이제부터 이 뒤는 전부 새로운 bit 값으로 보겠다는 뜻!
            current_state = bit
            
    print(f'#{tc} {count}')
'''
        

    
