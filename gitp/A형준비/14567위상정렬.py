from collections import deque

N,M= map(int,input().split())
graph=[[] for _ in range(N+1)] 
indegree = [0]*(N+1)
for _ in range(M):
    a,b=map(int,input().split())
    graph[a].append(b)
    indegree[b]+=1

semester = [0]*(N+1)
q=deque()

for i in range(1, N+1): #노드의 갯수만큼 
    if indegree[i]==0: #진입차수 가장 적은 것 부터 진입가능 
        q.append(i)
        semester[i]=1 #기록용 첫학기에는 이걸 들었다 왜냐면 선수과목이 없으니까 

while q:
    current = q.popleft()

    for next_node in graph[current]:
        indegree[next_node]-=1 #이 앞노드가 빠져서 next_node이므로 이땐 진입차수 1개씩 빠짐

        if semester[next_node]<semester[current]+1: #next_node는 당연히 현재 current 과목을 들은 다음 들을 수 있으니까 +1 해주는거 
            semester[next_node]=semester[current]+1 #이렇게 갱신하듯이 안하면 만약 선수과목 두개일때 값 최대한 뒤에껄로 못정함
            # 예를 들어 D듣기위해 A,B 들어야하는데 A1학기 B3학기면 처음엔 A1+1학기로 2학기때 듣는데 B때문에 결국엔 3+1 4학기에 들어야함
        
        if indegree[next_node]==0:
            q.append(next_node)
    
for i in range(1,N+1): #semester값으로 나열해서 학기마다 이수가능한 과목 개수 나타냄 
    print(semester[i],end=" ")

