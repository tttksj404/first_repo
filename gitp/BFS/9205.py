'''
일단 끝까지 갈 수 있을까 여부를 보는거니까 dfs 로 가능 
50미터에 1병 -> 20병 까지 괜찮으니까 1000미터를 맥주 한박스로 가는거
만약 페스티벌 까지 멘하튼 거리 보고 1000미터 넘으면 일단 편의점 들리기 -> 첫번쨰 편의점으로

첫 편의점에서 페스티벌 까지 멘하튼 거리 보고 1000미터 넘으면 두번쨰 편의점까지 들리기
근데 주의해야될껀 각 지점 사이의 거리가 1000미터 이내면 남은 맥주 개수까지 세어줘야함 
+=로 맥주개수 추가해주고 두번째 편의점까지 갔다면

마지막 페스티벌 까지 가는데 1병당 50 미터 최종으로 남은 맥주 개수가 페스티벌 까지의 거리 보다 크면 haapy
작으면 sad임 

하지만 일반 2차원 배열로 전체 맵을 구성하면 시간초과날 가능성 크므로 그냥 맵 구성안하고 풀 수 있는 bfs로 풀이해야함 


'''
import sys
from collections import deque

input = sys.stdin.readline

def bfs(start_idx):
    global can_reach
    while queue:
        # 성진님 스타일: 큐에서 현재 지점 인덱스를 꺼냄
        curr_idx = queue.popleft()
        curr_x, curr_y = coords[curr_idx] #지금 인덱스 값에서 가져온게 현재 좌표위치 

        # 목적지(페스티벌)에 도착했는지 확인
        if curr_idx == n + 1: #현재 인덱스가 페스티벌의 인덱스면 끝
            can_reach = True #도달여부 표시 
            return

        # 델타 탐색(상하좌우) 대신, 모든 좌표를 확인하며 '점프' 가능 여부 체크
        for next_idx in range(n + 2): #있는 좌표들 안에서 확인 
            if not visited[next_idx]:
                next_x, next_y = coords[next_idx] #다음 좌표설정
                
                # 맨해튼 거리 계산
                dist = abs(curr_x - next_x) + abs(curr_y - next_y)
                
                # 맥주 20병으로 갈 수 있는 거리(1000m) 이내라면
                if dist <= 1000:
                    visited[next_idx] = True
                    queue.append(next_idx)

# 테스트 케이스 개수 입력
T = int(input())

for _ in range(T):
    n = int(input()) # 편의점 개수
    
    # [집, 편의점들..., 페스티벌] 순서로 좌표 저장
    coords = [list(map(int, input().split())) for _ in range(n + 2)] #좌표를 한 리스트에다가 다 넣고 저장해서 풀이시작 아주 중요
    
    # 성진님 스타일: 방문 배열 및 큐 초기화
    visited = [False] * (n + 2) #좌표 다 넣었으니 집이랑 편의점 개수 페스티벌 포함하면 일단 집, 페스티벌 2개있으니까 편의점n에다가 +2해주는거
    queue = deque()
    can_reach = False # 도달 가능 여부 플래그
    
    # 시작 지점(집: 0번 인덱스) 설정
    visited[0] = True
    queue.append(0)
    
    # BFS 실행
    bfs(0)
    
    # 결과 출력
    if can_reach:
        print("happy")
    else:
        print("sad")
