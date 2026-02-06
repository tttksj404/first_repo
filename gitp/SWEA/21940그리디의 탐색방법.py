'''
T =int(input())
for w in range(1,T+1):

N은 조명의수
pattern = list(map(int,input().split()))
default = [0]*N 
count = 0
m번쨰 조명 클릭시 m배수 조명이 전부 영향받음
pattern의 1의 위치 인덱스로 전부 받아서 적어놓기
pattern에서 초반 1의 위치를 찾아 default에서 거기의 배수 까지 전부 1더해주고 count+=1
그다음 1의 위치 찾아 그 위치의 배수 전부 1 
다음 1위치 배수 전부 1
그 상태에서 이미 1이면 넘어가는 조건식 필요

다음 for 문으로 1의 인덱스 넣은거 돌리는데 default[]값에서 1안나오면 그인덱스 1전환해주고 count+=1
그렇게 끝까지 돌려서 1나오는지 확인 

print 하면됨



'''
T =int(input())
for w in range(1,T+1):
    N = int(input()) #패턴의 len
    pattern = list(map(int,input().split()))
    default = [0]*N
    count = 0
    idx_list = [] #1이 적힌 인덱스만 담아놓는 리스트
    for a in range(N): 
        if pattern[a] == default[a]: #참고로 인덱스 0 ->1이라는거 계속 기억
            pass
        elif pattern[a] != default[a]:
            count +=1
            if default[a] ==0: #코드의 변수 부분을 함부로 다른 변수와 같이 반복문에 넣지 않게 주의 
                default[a] =1
            elif default[a] ==1:
                default[a] =0
            for b in range(a,N,a+1):#a의 배수 쩜프 배수볼땐 전구의 인덱스로 점프 불러와서 애초에 아래 if 필요 x 
                #if b>=a and b+1 %(a+1) ==0: #전구 번호로 인덱스 봐야함 
                    if default[b] == 0: #실제 인덱스 값으로 할땐 상관없으나 위에 a의 배수인지 알아볼땐 전구의 인덱스 번호로 비교해야됨
                        default[b] = 1
                    elif default[b] ==1:  
                        default[b] =0
    #1을 0으로 0을 1로 바꾸는건 
    #default[b] = 1 - default[b] 이런식으로 해도 가능 
    #한줄로 커버가능 
    
    print(f'#{w} {count}')
#조건에 해당하는 값만 찾아가는게 그리디의 전형적인 탐색방법
#조건 만족할때 반복문 돌아감 
#반대로 반복문 돌리면서 조건찾는건 그리디가 아님 




        



