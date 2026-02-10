# %2 반복해서 나머지 값이 1이냐 0이냐로 이진수 추출가능 처음 나머지 값 1 그다음 2로 나눴을때 나머지 값
'''
N = int(input())
ans=[]
dp=[0]*(N+1)
pd=[0]*(N+1)
#dp[1]부터 시작?
dp[1]=N//2
pd[1]=N%2
for i in range(2,N+1):
    dp[i]=dp[i-1]//2
    pd[i]=dp[i-1]%2
print(pd[N])
'''

N = int(input())


if N ==0:
    print(0)

else:
    ans=[]
    while N>0:
        ans.append(str(N%2))
        N//=2
    
    print("".join(ans[::-1]))



'''
import sys
# 입력 숫자가 커도 재귀 깊이가 깊지 않아서 (약 47단계) 
# setrecursionlimit을 따로 건드릴 필요도 없습니다.
input = sys.stdin.readline

def convert_to_binary(n):
    # 기저 조건: 더 이상 나눌 수 없으면 멈춤
    if n == 0:
        return

    # 재귀 단계: 2로 나눈 몫을 가지고 다시 나를 호출 (더 작은 문제로 쪼개기)
    convert_to_binary(n // 2)
    
    # 출력 단계: 호출이 다 끝나고 "돌아오는 길"에 나머지를 출력
    # 이렇게 하면 자연스럽게 역순(이진수 순서)으로 출력됩니다.
    print(n % 2, end='')

N = int(input())

if N == 0:
    print(0)
else:
    convert_to_binary(N)
    print() # 줄바꿈

'''

