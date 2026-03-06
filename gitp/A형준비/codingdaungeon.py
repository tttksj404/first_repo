'''
🔍 [문제 분석: 코딩 던전 탐험]
이 문제는 주어진 골드(K) 내에서 출발지(0번 노드)로부터 도달 가능한 모든 던전을 찾는 그래프 탐색 문제입니다.
각 경로는 '입장료(가중치)'가 있으며, 여러 경로를 거칠 때마다 이 가중치가 누적됩니다.

🏗️ [설계 체크리스트]
1. 그래프 빌드: 인접 리스트(`graph`)를 사용하여 양방향 연결 상태와 가중치를 저장한다.
2. 탐색 전략: DFS를 사용하여 깊이 있게 탐색하며, 누적 가중치가 예산(K)을 초과하지 않는지 체크한다.
3. 방문 처리: `visited` 배열을 -1로 초기화하여 방문 여부와 동시에 '해당 노드까지의 최소 비용'을 기록할 수 있게 준비한다.
4. 결과 정리: 방문한 노드들을 `storage`에 담고, 중복 제거 및 정렬하여 출력한다.
'''

T = int(input())
for tc in range(1, T + 1):
    # N: 던전 수, M: 경로 수, K: 보유한 골드
    N, M, K = map(int, input().split())

    # 1. 그래프 구성 (1~N번 던전 + 0번 출발지 포함)
    graph = [[] for _ in range(N + 1)] 
    storage = [] # 도달 가능한 던전 번호를 저장할 리스트

    for _ in range(M):
        a, b, w = map(int, input().split())
        # 양방향 연결: a에서 b로 갈 때 w만큼 골드 소모
        graph[a].append((b, w))
        graph[b].append((a, w))

    '''
    🚀 [코딩 로직: DFS 탐색 함수]
    - node: 현재 위치한 던전 번호
    - current_dist: 현재까지 소모한 총 골드 누적합
    - visited: 각 노드 방문 여부 체크 배열
    '''
    def dfs(node, current_dist, visited):
        # 0번(출발지)이 아닌 실제 던전에 도착했다면 기록!
        if node != 0:
            storage.append(node)

        # 현재 노드 방문 표시 (지금까지 소모한 골드 저장)
        visited[node] = current_dist 

        # 현재 위치에서 갈 수 있는 다음 던전들 확인
        for next_node, weight in graph[node]:
            # [조건 1] 아직 방문하지 않은 던전인가?
            if visited[next_node] == -1:
                # [조건 2] 다음 던전까지 가는데 예산(K)이 충분한가?
                if current_dist + weight <= K:
                    # 모든 조건 만족 시 다음 던전으로 Go!
                    dfs(next_node, current_dist + weight, visited)

    # 2. 탐색 시작
    # visited1[i] == -1이면 미방문, 0 이상이면 방문 시 소모된 골드
    visited1 = [-1] * (N + 1)
    dfs(0, 0, visited1)

    # 3. 결과 처리 (중복 제거 후 오름차순 정렬)
    # DFS 특성상 여러 경로로 같은 노드를 갈 수 있으므로 set으로 중복 제거 필수!
    storage = sorted(list(set(storage)))

    # 4. 정답 출력
    print(f'#{tc}', *storage)

'''
💡 [학생 가이드 & 실전 팁]
1. "누적 가중치"가 있는 DFS/BFS 문제에서는 항상 '다음 지점의 가중치'를 더했을 때 
   한계치(K)를 넘지 않는지 먼저 검사하는 습관을 들이세요! (백트래킹의 기초)
2. 만약 이 문제에서 "최단 거리"를 구해야 했다면 DFS보다는 BFS나 다익스트라(Dijkstra)가 더 유리합니다.
3. 중복 노드 저장을 방지하기 위해 `storage`를 리스트 대신 처음부터 `set()`으로 선언하는 것도 좋은 방법입니다.
4. `visited` 배열에 단순히 True/False만 넣지 않고, `current_dist`를 저장하면 
   나중에 "특정 지점까지 몇 골드로 갔지?"라는 질문에도 바로 대답할 수 있어 확장에 유리합니다.
'''






