'''
0,1,0,2,1,4,1,3 이러면  0->1->3 이렇게 나아감 
그렇게 나아가서 0이 99에 도달 할 수 있으면 1이고 안되면 0나옴 


'''

for _ in range(10):
    tc, len_data = map(int,input().split())
    raw_data = list(map(int,input().split()))
    graph = {} #딕셔너리로 키->벨류->키 순서대로 이어가는 로직 
    for i in range(0,len(raw_data),2): #2씩 점프해서 시작점은 시작점 대로 / 끝점은 끝점대로 
        start_node = raw_data[i] 
        end_node = raw_data[i+1]

        if start_node not in graph: #딕셔너리 안에 시작점의 끝점이 없더라도 만들어 놓긴 해야지 연결되는지 안되는지 판단가능함
            graph[start_node]=[] #시작점이 딕셔너리에 없다면 시작점 자체는 추가하지만 해당 끝값은 당연히 없는걸로 빈 리스트
             #시작점에 대한 도착 하는 value값들을 저장하는 리스트
        graph[start_node].append(end_node) #raw_data[i]에 키 start 값 / raw_data[i+1]에 벨류 end 값 값 
    stack = [0] #출발점 0을 스택에 넣고 시작함 
    visited=[] #dfs 가장 중요한 방문여부 판단
    result = 0 

    while stack: #스택에 딕셔너리의 벨류값이 들어가고 그 값을 다시 키로 꺼내고 다시 벨류값 넣는과정 반복
        current = stack.pop() #지금 위치는 스택에서 이전에 넣었던 키의 벨류값 즉= 지금의 출발점을 꺼내는거니까 last in first out 마지막이 가장 처음 출발점

        if current ==99: #스택에서 뽑았던건 이전 키 값의 벨류값이 99라는건 이미 목표99에 도달했다는 것
            result = 1
            break #목표 도달해서 더이상 확인 필요 x
        if current not in visited: #스택에서 벨류값이 키값으로 옮겨져서 다시 벨류값 찾으려는데 시작할 벨류값이 visited에 없으면
            visited.append(current) #방문안했으면 이제 방문한거니까 방문했다는 리스트에 넣기
            if current in graph: #방문했으니 현재값이 이제 벨류에서 키로 변해서 다시 스택에 추가되는 과정#현재 시작점이 그래프에 있으면  
                stack.extend(graph[current]) #스택에 그래프의 현재 시작점의 도착점들을 다 넣기 
    print(f'#{tc} {result}')           





