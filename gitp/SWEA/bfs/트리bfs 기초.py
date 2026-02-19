import sys
from collections import deque

# 1. 입력 최적화 (M2 맥북의 성능을 제대로 쓰기 위해 필수)
# input = sys.stdin.readline 

def solve():
    # N: 노드의 개수 (보통 1번부터 N번까지 존재)
    N = int(input())
    
    # 2. 인접 리스트(adj) 초기화
    # N+1인 이유는 0번 인덱스를 버리고 1번부터 N번까지 편하게 쓰기 위함입니다.
    adj = [[] for _ in range(N + 1)]
    
    # 3. 연결 정보 입력 (트리는 노드가 N개면 간선은 항상 N-1개입니다)
    for _ in range(N - 1):
        u, v = map(int, input().split())
        # 트리는 보통 무방향이므로 양쪽에 추가합니다.
        adj[u].append(v)
        adj[v].append(u)

    # 4. BFS 함수 시작
    def bfs(start_node):
        # 큐 생성 및 시작 노드 삽입
        queue = deque([start_node])
        
        # 방문 체크 배열 (중복 방문 방지)
        visited = [False] * (N + 1)
        visited[start_node] = True
        
        while queue:
            # 큐의 맨 앞에서 노드를 하나 꺼냅니다.
            curr = queue.popleft()
            print(f"현재 방문한 노드: {curr}") # 실전에서는 여기서 점수 계산 등을 함
            
            # 현재 노드(curr)와 연결된 친구(neighbor)들을 하나씩 확인
            for neighbor in adj[curr]:
                if not visited[neighbor]:
                    # 아직 안 가본 곳이라면 큐에 넣고 방문 처리
                    visited[neighbor] = True
                    queue.append(neighbor)

    # 1번 노드를 뿌리(Root)로 가정하고 BFS 실행
    bfs(1)

# --- 예시 입력 데이터 (N=4, 연결 정보 3개) ---
'''
4
1 2
1 3
2 4
'''
solve()