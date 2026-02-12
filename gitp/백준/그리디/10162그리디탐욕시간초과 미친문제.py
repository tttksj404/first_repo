'''
t초가 주어지고 만약에 t >=300 안되면 a 안됨 / t>=60 안되면 b 안됨 
a 5분 -> 300초
b 1분 -> 60초
c 10초 -> 10초
그리고 최소 동작임 

a먼저 처리후에 b 처리 후에 c처리 

'''
''' 이건 시간초과남 
T = int(input())
a_count=0 #300
b_count = 0 #60
c_count = 0 #10
while T !=0:
    if T>=300:
        a_count+=1
        T-=300
    if 60<=T<300:
        b_count+=1
        T-=60
    if T<60:
        c_count+=1
        T-=10
    if 0<T<10:
        print(-1)
        break

print(f'{a_count} {b_count} {c_count}')
'''

#9900- a 33번 하고 나머지 100에 대해서 b 1번 나머지 40에 대해 c 4번 총 38번이 최대 
T = int(input())

# 10초 단위로 맞출 수 없는 경우 (10으로 나누어 떨어지지 않는 경우)
if T % 10 != 0:
    print(-1)
else:
    # A 버튼 (300초 = 5분)
    a_count = T // 300
    T %= 300 # A로 채우고 남은 시간
    
    # B 버튼 (60초 = 1분)
    b_count = T // 60
    T %= 60 # B로 채우고 남은 시간
    
    # C 버튼 (10초)
    c_count = T // 10
    T %= 10 # 사실 위에서 이미 10의 배수임을 확인했으므로 여기서는 T가 0이 됨
    
    print(f"{a_count} {b_count} {c_count}")

    


        #반복문 사용안하고 풀이가능 