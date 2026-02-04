'''
테스트케이스
고객의수
고객 수 각자에게 부과된 기본요금
요금 요청의 개수
요금요청의 개수만큼 반복
요금요청 실제 내용 받고 처리


'''
'''
T = int(input())
for w in range(1,T+1):
    N = int(input())
    default_cost = list(map(int, input().split()))
    quest_num = int(input())
    for n in range(quest_num):
        quest = list(map(int, input().split()))
        quest_start = quest[0] #1 초기 인덱스 값
        quest_end = quest[1] #3 끝 인덱스 값
        quest_change = quest[2] #10 각 인덱스 에서 더하거나 빼줘야 하는 값 
        quest_for = quest_end-quest_start+1
        for idx in range(quest_start , quest_end+1):
            default_cost[idx]+=quest_change
    print(f'#{w}',*default_cost)
'''
'''
T = int(input())
for w in range(1,T+1):
    N = int(input())
    default_cost = list(map(int, input().split()))
    quest_num = int(input())
    for n in range(quest_num):
        s,e,v = map(int, input().split())
        for idx in range(s, e):
            default_cost[idx]+=v
    print(f'#{w}',*default_cost)
'''
#위의 식들은 1초내에 못품
import sys
# input() 보다 훨씬 빠른 읽기 방식입니다. (10만 건 이상 데이터 필수)
input = sys.stdin.readline

# 1. 테스트케이스 개수 입력
T_str = input().strip()
if T_str:
    for t in range(1, int(T_str) + 1):
        # 2. 고객 수(N)와 기본 요금 리스트 입력
        N = int(input())
        costs = list(map(int, input().split()))
        
        # 3. 차분 배열(diff) 생성  #변화량 자체를  저장한 배열 
        # e+1 지점을 건드려야 하므로 N+1 크기로 
        diff = [0] * (N + 1)
        
        # 4. 요금 조정 요청(P) 처리
        P = int(input())
        for _ in range(P):
            s, e, v = map(int, input().split()) #값 자체를 리스트로 안받고 각 변수로 받아도 상관없음 
            
            # 시작 지점에 요금 더하기 
            diff[s] += v
            
            # 끝 지점 다음 칸에 요금 빼기 
            # e+1이 고객 범위를 벗어나지 않을 때만 표시합니다.
            if e + 1 < N:
                diff[e + 1] -= v
        
        # 5. 누적합(Prefix Sum) 계산하며 최종 요금 산출
        # 이 과정이 100억 번의 연산을 10만 번으로 줄여주는 마법의 구간입니다.
        current_v = 0 # 현재 흐르고 있는 요금 조정값
        for i in range(N):
            current_v += diff[i] # 앞에서부터 흘러온 값을 누적
            costs[i] += current_v # 누적된 값을 기본 요금에 반영 
            #누적합에서 계산가능 
        
        # 6. 결과 출력 (* 기호는 리스트를 공백으로 풀어서 출력해줍니다)
        print(f"#{t}", *costs)