'''
그래프 문제
'''

n = int(input())
target_one, target_second = map(int, input().split())
m = int(input())
graph=[[] for _ in range(n+1)] #변수 이름 주의하기 그리고 범위 보통 1부터 시작하니까 +1해주기
visited = [False]*(n+1)
for a in range(m):
    mother,son= map(int,input().split())
    graph[mother].append(son)
    graph[son].append(mother) #이렇게 반대의 경우도 넣어줘야함을 주의
count=0 #count를 쓰면 틀린길로 가서 돌아올때도 +1씩 추가되므로 
#dfs 함수내에서 따로 깊이를 또 다른 변수로 추가해서 관리해주기 
result= -1 #이런 예외값은 먼저 정해주고, 따로 조건줘서 변동하도록 해주기


def dfs(start, end,chon): #함수의 변수값으로 조정해주는게 아주좋음 
    global result
    visited[start]=True

    if start==end:
        result=chon
        return
    
    for next_node in graph[start]:
        if not visited[next_node]:
            dfs(next_node,end,chon+1)

    
        
        
dfs(target_one,target_second,0)
print(result)

