'''
📍 [백준 2573] 빙산 - BFS & 시뮬레이션 (IM 초월 최적화 버전)

🔍 1. 문제 분석 (현실 로직)
- 빙산이 바다(0)에 둘러싸여 있으며, 매년 사방의 바다 개수만큼 녹아내림.
- 핵심은 '동시에' 녹는다는 것. A가 녹아서 0이 되었다고 해서, 같은 년도에 계산하는 B가 A를 바다로 인식하면 안 됨.
- 빙산이 두 덩어리 이상으로 갈라지는 최초의 시간을 구해야 함. 만약 다 녹을 때까지 안 갈라지면 0 출력.

💡 2. 핵심 알고리즘 설계 (코딩 로직)
- [최적화 1] 명단 관리 (ice_list): 300x300 지도를 매번 뒤지는 건 바보 같은 짓! 빙산 위치만 따로 적어두고 걔들만 감시하자.
- [최적화 2] 예약 시스템 (melt_list): "너 이번에 3만큼 녹을 거야"라고 메모만 해두고, 조사가 다 끝나면 한꺼번에 깎기 (스냅샷).
- [최적화 3] 명단 다이어트 (next_ice_list): 다 녹아서 0이 된 애들은 다음 해 명단에서 즉시 퇴출. 갈수록 빨라지는 마법!

🏗️ 3. 구현 체크리스트
1) 초기 ice_list 생성 (빙산 좌표만 수집)
2) 루프 시작:
   - 덩어리 개수 체크 (BFS): ice_list의 첫 번째 요소부터 시작해서 몇 번 BFS를 돌려야 다 방문하는지 확인.
   - 덩어리가 2개 이상이면 종료 및 년도 출력.
   - 빙산 녹이기 (예약): ice_list를 돌며 사방의 0 개수 파악 -> melt_list에 저장.
   - 실제 반영: melt_list 적용 (max(0, 현재-녹을양)).
   - 명단 갱신: 살아남은 빙산만 next_ice_list로 교체.
   - 년도(year) + 1.
3) 루프 종료 시까지 답이 안 나오면 0 출력.
'''

from collections import deque
import sys
input = sys.stdin.readline

# 1. 입력 받기 및 초기화
N, M = map(int, input().split())
grid = []
ice_list = [] # 📍 [핵심] 빙산의 좌표만 관리하는 '용의자 명단'

for r in range(N):
    row = list(map(int, input().split()))
    grid.append(row)
    for c in range(M):
        if row[c] > 0:
            ice_list.append((r, c)) # 빙산 위치만 딱 골라내기

# 방향 벡터 (상하좌우)
dr = [-1, 1, 0, 0]
dc = [0, 0, -1, 1]

# 2. 덩어리 개수를 세는 함수 (BFS)
def get_chunk_count(current_ice):
    if not current_ice: return 0
    
    visited = [[False] * M for _ in range(N)]
    chunks = 0
    
    for r, c in current_ice:
        # 명단에 있어도 이미 다른 덩어리 탐색 때 방문했을 수 있으니 체크
        if grid[r][c] > 0 and not visited[r][c]:
            # 새로운 덩어리 발견! BFS 시작
            queue = deque([(r, c)])
            visited[r][c] = True
            
            while queue:
                curr_r, curr_c = queue.popleft()
                for i in range(4):
                    nr, nc = curr_r + dr[i], curr_c + dc[i]
                    # 범위 내에 있고, 빙산이며, 아직 방문 안 했다면 같은 덩어리
                    if 0 <= nr < N and 0 <= nc < M:
                        if grid[nr][nc] > 0 and not visited[nr][nc]:
                            visited[nr][nc] = True
                            queue.append((nr, nc))
            
            chunks += 1 # 한 덩어리 탐색 끝!
            
    return chunks

# 3. 메인 시뮬레이션 루프
year = 0
while ice_list:
    # [Step 1] 현재 상태에서 덩어리 개수 파악
    num_chunks = get_chunk_count(ice_list)
    
    # 덩어리가 2개 이상으로 갈라졌다면 정답!
    if num_chunks >= 2:
        print(year)
        break
    
    # [Step 2] 빙산 녹이기 (예약 시스템/스냅샷)
    # 📍 중요: 즉시 grid를 수정하면 옆 칸 연산이 오염됩니다!
    melt_info = [] # (행, 열, 녹을 양) 저장
    
    for r, c in ice_list:
        sea_count = 0
        for i in range(4):
            nr, nc = r + dr[i], c + dc[i]
            if 0 <= nr < N and 0 <= nc < M:
                if grid[nr][nc] == 0:
                    sea_count += 1
        
        if sea_count > 0:
            melt_info.append((r, c, sea_count))
            
    # [Step 3] 예약된 정보 일괄 반영 (Batch Update)
    for r, c, melt_amount in melt_info:
        # max(0, ...)를 사용하여 0 미만으로 떨어지는 것을 방지하는 깔끔한 처리
        grid[r][c] = max(0, grid[r][c] - melt_amount)
        
    # [Step 4] 명단 다이어트 (살아남은 빙산만 추리기)
    # 이미 0이 된 빙산은 내년에 검사할 필요가 없습니다.
    next_year_ice = []
    for r, c in ice_list:
        if grid[r][c] > 0:
            next_year_ice.append((r, c))
            
    ice_list = next_year_ice # 명단 갱신
    year += 1 # 1년 경과

else:
    # 빙산이 다 녹을 때까지 2덩어리 이상으로 갈라지지 않은 경우
    print(0)

'''
💡 [학생 가이드: 실전 합격 팁]
1. "전수 조사는 죄악이다": 300x300 맵에서 빙산은 갈수록 줄어듭니다. ice_list를 써서 탐색 범위를 압축하는 것이 A형 합격의 필수 소양입니다.
2. "스냅샷(Snapshot)의 마법": 동시에 일어나는 일은 항상 '임시 리스트'에 모았다가 한꺼번에 반영하세요. 안 그러면 연쇄 반응으로 답이 꼬입니다.
3. "다이어트(Dieting)": 필요 없는 정보는 즉시 버리세요. 시간이 흐를수록 연산 속도가 빨라지게 만드는 것이 프로그래밍의 묘미입니다.
'''
