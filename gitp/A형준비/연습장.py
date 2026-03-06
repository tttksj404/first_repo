
def find(x):
    if x!=parent[x]: #내가 내 대장이 아니라면 
        parent[x] = find(parent[x]) #진짜 대장을 찾아서 나를 바로 그 밑에 붙여버림 
    return parent[x]

def union(a,b):
    a= find(a) #a의 대장을 찾아오고
    b= find(b)# b의 대장을 찾아와서 
    if a!=b: #둘 대장이 다르면 (다른 팀이면)
        parent[b]=a #b팀 대장을 a팀 대장 밑으로 넣어서 한팀으로 만듦 



T = int(input())
for tc in range(1,T+1):
    N,Q= map(int,input().split())
    parent = [i for i in range(N+1)]
    query = []
    for _ in range(Q):
        K,A,B= map(int,input().split())
        if K==1:
            union(A,B)
        else:
            A= find(A)
            B= find(B)
            if A==B:
                query.append("YES")
            else:
                query.append("NO")
    print(f'#{tc}',*query)
