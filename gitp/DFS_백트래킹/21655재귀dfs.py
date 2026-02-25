'''
n*n에서 1찾고 그 1이 있는 인덱스 값 [i][j]은 [i]번 노드 -> [j]번 노드로 이동한다는걸 뜻함 
(0,2)이면 0->2 그럼 2에서 출발하는 노드 찾아야하므로 stack에다가 2 넣고 [2][j]에서 1의 값 찾기 

'''
def dfs(v):
    visited[v] = True #방문한 값 true 전환 default값이 false이기 때문에 
    print(v, end=' ') #여기선 이미 값 출력 뒤에 다시 재귀호출하는거라 순서 신경x 
    #만약 프린트가 dfs(next_v)보다 뒤였으면 아마 순서 거꾸로 출력되었을것 

    for next_v in graph[v]: #담아놨던 1인 좌표값 노드 전부 불러오기 
        if not visited[next_v]: 
            #다음에 담아놓을 next_v가 방문된 리스트 값에 없다면 방문x그래서 방문하러 
            #재귀호출
            dfs(next_v) #0부터  시작해서 그래프에 있는 1의 값의 좌표들 전부 재귀하면서 돌게됨
            

T = int(input())
for w in range(1,T+1):
    N = int(input())
    data = [list(map(int, input().split())) for _ in range(N)]
    visited = [False]*N
    graph = [[] for _ in range(100)]
    for a in range(N):
        for b in range(N):
            if data[a][b] ==1: #a가 스타트 노드 그다음 b가 다음 노드임 
                graph[a].append(b) 
                #스타트 값을 리스트에 담기 뿐만 아니라 1되는 모든 값을 다 넣어놓기

    print(f'#{w}', end=' ')
    dfs(0)
    print()



    

    
    










