'''
짝수 = n//2 -> 1이 됨 
홀수 = m*3+1 -> 1이 됨 
함수를 짝수, 홀수로 적어주고 재귀호출 돌리면됨

'''

def zzak(z):
    global count
    if z%2 ==0:
        next_h = z//2
        if next_h %2==1:
            count+=1
            return holl(next_h)
        elif next_h %2==0:
            count+=1
            return zzak(next_h)



def holl(h):
    global count
    if h==1:
        return count  
    if h%2==1:
        next_z = h*3+1
        if next_z %2==0:
            count+=1
            return zzak(next_z)
        elif next_z %2 ==1:
            count+=1
            return holl(next_z)

T = int(input())
for w in range(1,T+1):
    fisrt_num = int(input())
    count = 0
    if fisrt_num%2==0:
        print(f'#{w} {zzak(fisrt_num)}')
    else:
        print(f'#{w} {holl(fisrt_num)}')
    

'''
# 정석 코드 (반복문 사용)
T = int(input())
for w in range(1, T+1):
    num = int(input())
    count = 0
    
    # num이 1이 될 때까지 무한 반복
    while num != 1:
        if num % 2 == 0:
            num = num // 2
        else:
            num = num * 3 + 1
        count += 1 # 한 번 처리했으니 카운트 증가
        
    print(f"#{w} {count}")
'''

'''
def solve(n):
    global count # 바깥에 있는 count를 쓸 거야!
    
    if n == 1: # 1이 되면 끝!
        return

    count += 1 # 횟수 증가
    
    if n % 2 == 0:
        solve(n // 2) # 짝수면 반토막 내서 다시 던짐
    else:
        solve(n * 3 + 1) # 홀수면 3배+1 해서 다시 던짐

T = int(input())
for w in range(1, T+1):
    num = int(input())
    count = 0 # 테스트 케이스마다 초기화
    solve(num)
    print(f"#{w} {count}")
'''