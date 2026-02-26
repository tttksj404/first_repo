'''
그래프를 만드는데 +1,-1 이어주는 노드 만들고 거기서 2* 하는 노드도 만들어야함 
그렇게 그래프 만들고, bfs로 최소시간 거리 찾기

[스스로 피드백: 내가 부족했던 부분]
1. 인덱스 범위 초과 주의: 2* 연산 시 100,000을 넘을 수 있는데, visited 리스트의 인덱스 범위를 체크하는 조건(0 <= neighbor < 100001)이 필수다.
2. 불필요한 그래프 생성: 이동 규칙이 명확(+1, -1, *2)할 때는 굳이 graph 리스트를 미리 만들지 말고, 탐색할 때 즉석에서 계산하자.
3. 거리(시간) 기록 방식: count 변수로 전체 pop 횟수를 세는 게 아니라, visited[neighbor] = visited[current] + 1을 통해 '단계(깊이)'를 기록해야 한다.
4. 예외 케이스: 시작점과 도착점이 처음부터 같은 경우(N == K)를 항상 먼저 체크하자.
5. 변수 관리: 함수 내에서 정의되지 않은 변수(count 등)를 쓰지 않도록 주의하고, 방문 체크와 거리 기록을 동시에 하는 요령을 익히자.

[추천 연습 문제]
- 백준 13913 (숨바꼭질 4): 이동 경로까지 출력해보기
- 백준 12851 (숨바꼭질 2): 가장 빠른 방법이 몇 가지인지 세어보기
- 백준 13549 (숨바꼭질 3): 순간이동은 0초가 걸리는 경우 (0-1 BFS)
- 백준 2178 (미로 탐색): 2차원 배열에서의 기본적인 BFS 거리 측정
'''

from collections import deque


N,K= map(int,input().split()) #N은 수빈이 위치 / K는 동생 위치 타겟


def bfs(start,end):
    # 시작과 동시에 도착한 경우 처리
    if start==end:
        return(1)

    queue = deque([start])
    visited = [0]*100001
    visited[start]+=1

    while queue:
        current = queue.popleft()

        # 이동 가능한 3가지 위치 탐색
        for neighbor in (current-1,current+1,current*2):
            # 1. 인덱스 범위 내에 있고 2. 아직 방문하지 않은 경우
            if 0 <= neighbor < 100001 and visited[neighbor]==0:
                visited[neighbor]=visited[current]+1
                
                # 도착 시 현재까지 기록된 시간 반환
                if neighbor == end:
                    return visited[neighbor]
                
                queue.append(neighbor)
            
    return(-1)

# 시작 시 +1을 했으므로 최종 결과에서 1을 빼줌
print(bfs(N,K)-1)
