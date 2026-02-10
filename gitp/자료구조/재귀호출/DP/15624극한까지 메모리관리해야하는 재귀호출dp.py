'''
def selfcall(s):
    if s <=1:
        return s
    
    return selfcall(s-1) + selfcall(s-2)
N = int(input())
result = list(selfcall(N))
ans = result[N-1]//1000000007
print(ans)
#이게 일반적인 재귀 코드 
''' 
'''

def fibo_tab(n):
    # 1. 필요한 크기만큼 테이블 생성
    dp = [0] * (n + 1)
    dp[1], dp[2] = 1, 1
    
    # 2. 작은 문제부터 차례대로 루프를 돌며 해결
    for i in range(3, n + 1):
        dp[i] = dp[i-1] + dp[i-2]
        
    return dp[n]


N = int(input())
result = fibo_tab(N)
print(result)
'''
'''
# 계산된 값을 저장할 사전(Dictionary) 또는 배열
import sys
sys.setrecursionlimit(10**6)
input = sys.stdin.readline
memo = {}

def fibo_memo(n):
    # 1. 이미 계산한 적이 있다면 즉시 반환 (중복 호출 방지)
    if n in memo:
        return memo[n]
    
    # 2. 기저 상태
    if n <= 2:
        return 1
    
    # 3. 재귀적으로 호출하되 결과를 memo에 기록
    memo[n] = fibo_memo(n-1) + fibo_memo(n-2)
    return memo[n]


N = int(input())
result = fibo_memo(N)
print(result)
'''
import sys
input = sys.stdin.readline

n = int(input())

    # 1.000.000.007로 나눈 나머지를 저장할 테이블
dp = [0] * (n + 1) #n이 1000000만 번까지가 최대값이라서 이렇게 나타냄 
dp[1] = 1 #초기값은 적어줘야함
dp[2] = 1 #초기값은 적어줘야함
    
MOD = 1000000007
    
for i in range(3, n + 1): #3부터 시작하기 때문에  3번째 수부터는 이전값 활용가능해서 반복문 
    # 계산할 때마다 나머지를 구해주어야 숫자가 커지지 않습니다
    dp[i] = (dp[i-1] + dp[i-2]) % MOD #점화식 
        
print(dp[n])


