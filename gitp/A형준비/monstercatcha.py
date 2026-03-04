'''
dfs 로 min값 순회 가능
그러나 
다익스트라 bfs로 최소값 보장도 가능하긴함 
'''


def dfs(current_pos, candidates, current_dist):
    global min_dist

    if current_dist>=min_dist: #지금 까지의 거리합이 최소 거리합을 넘었으면 볼필요도 없음 
        return
    
    if len(candidates)==0: #더 이상 나아갈 후보가 없다면 지금까지의 거리 합을 최소 거리합을 갱신
        if current_dist< min_dist:
            min_dist=current_dist
        return
    
    for i in range(len(candidates)):#갈 수 있는 후보지들 하나씩 가보자
        target= candidates.pop(i) #후보지들 가면서 갈때 그 후보지에서 하나씩 뽑아서 꺼내놓기 근데 나중에 insert 해줄생각은 해야함 재귀하기전
        #재귀전 insert안해주면 범위 에러나서 못품

        #여긴 이동 거리 계산하는곳
        target_pos= locations[target]
        dist = abs(current_pos[0]-target_pos[0]) + abs(current_pos[1]-target_pos[1]) #행렬 좌표값 멘하튼 거리로 계산

        if target>0: #후보들 중 뽑은 타겟이 몬스터(양수)면 다음에 후보는 당연히 고객(음수)이 언제인지는 모르나 후보에 들어가게됨
            candidates.append(-target) #해당되는 몬스터에 음수값이 고객이니까 -> 해당되는 문스터를 잡을때만 생기는 기회가지고 dfs 다 돌렸으면 다른 몬스터로 시작하는걸 봐야하기에 
            #일단 초기화가 필요하게 된다
            dfs(target_pos,candidates,current_dist+dist) #지금까지의 거리합에 새로가는 곳의 거리합 더해주기 
            candidates.pop() #돌아와서는 추가했던 고객을 다시 제거해주기 
            #몬스터->고객의 순서가 조건이므로 / 고객-> 몬스터는 안되니까 
        
        else: #후보들중 뽑은 타겟이 고객(음수)면 이미 몬스터 잡고 간거라서 그까지의 거리합을 더해주면 해결됨 
            dfs(target_pos,candidates,current_dist+dist)

        candidates.insert(i,target) #위의 for 문에서 pop한게 있어서 그쪽을 극복하고자 복구 해주는것 

T= int(input())
for tc in range(1,T+1):
    N=int(input())
    monster_map = [list(map(int,input().split())) for _ in range(N)]
    min_dist=999999
    locations = {}
    inital_monsters = []
    for i in range(N):
        for j in range(N):
            value = monster_map[i][j]
            if value !=0:
                locations[value]=(i,j)

                if value>0: 
                    inital_monsters.append(value) #몬스터를 먼저 값에다가 넣어야하기 때문임 

    dfs((0,0),inital_monsters,0)
    print(f'#{tc} {min_dist}')


    #여기 아래는 다익스트라로 풀이하는 방법 

    import heapq

# 거리 계산 함수 (맨해튼 거리)
def get_dist(p1, p2):
    return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])

def solve():
    # 입력 처리 (여기서만 컴프리헨션 사용)
    T_str = input()
    if not T_str:
        return
    T = int(T_str)

    for tc in range(1, T + 1):
        N = int(input())
        matrix = []
        for _ in range(N):
            matrix.append(list(map(int, input().split())))

        # 1. 주소록 만들기
        mon_pos = {}
        cus_pos = {}
        for r in range(N):
            for c in range(N):
                val = matrix[r][c]
                if val > 0:
                    mon_pos[val] = (r, c)
                elif val < 0:
                    cus_pos[abs(val)] = (r, c)

        M = len(mon_pos)
        
        # 2. 모든 목적지(몬스터+고객) 좌표를 하나의 리스트에 정리
        # 0 ~ M-1: 몬스터, M ~ 2M-1: 고객
        all_locs = []
        for i in range(1, M + 1):
            all_locs.append(mon_pos[i])
        for i in range(1, M + 1):
            all_locs.append(cus_pos[i])
        
        # 시작점 (0,0)을 마지막 인덱스에 추가
        num_targets = 2 * M
        all_locs.append((0, 0))
        start_idx = num_targets

        # 3. 최단 거리 장부 (dist_table[방문상태][현재위치])
        # max_mask는 2의 num_targets승 (비트마스크)
        max_mask = 1 << num_targets
        dist_table = []
        for _ in range(max_mask):
            row = []
            for _ in range(num_targets + 1):
                row.append(99999999) # 아주 큰 수로 초기화
            dist_table.append(row)

        # 4. 우선순위 큐 준비 (시간, 현재_인덱스, 방문_상태)
        pq = []
        heapq.heappush(pq, (0, start_idx, 0))
        dist_table[0][start_idx] = 0

        final_ans = 0

        while pq:
            curr_time, curr_idx, mask = heapq.heappop(pq)

            # 이미 찾은 더 짧은 길이 있다면 무시
            if curr_time > dist_table[mask][curr_idx]:
                continue

            # 모든 곳을 방문했다면 종료 (다익스트라 특성상 가장 먼저 도착한 게 최단거리)
            if mask == max_mask - 1:
                final_ans = curr_time
                break

            # 다음 갈 곳을 하나씩 검사
            for next_idx in range(num_targets):
                # 아직 안 간 곳인가?
                if not (mask & (1 << next_idx)):
                    
                    # 배달(고객)이라면 몬스터를 잡았는지 확인
                    can_go = True
                    if next_idx >= M:
                        monster_idx = next_idx - M
                        # 몬스터 비트가 0이면 아직 안 잡은 것
                        if not (mask & (1 << monster_idx)):
                            can_go = False
                    
                    if can_go:
                        # 이동 시간 계산
                        d = get_dist(all_locs[curr_idx], all_locs[next_idx])
                        next_time = curr_time + d
                        next_mask = mask | (1 << next_idx)

                        # 더 짧은 시간을 찾았다면 갱신하고 큐에 삽입
                        if next_time < dist_table[next_mask][next_idx]:
                            dist_table[next_mask][next_idx] = next_time
                            heapq.heappush(pq, (next_time, next_idx, next_mask))

        print(f"#{tc} {final_ans}")

solve()