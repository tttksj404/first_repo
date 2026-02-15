'''
b 
o
1. b1->b2 
2. b2 누르기
3. o1 누르기, b3이동
4. o2 이동,b4이동
5. o2누르기
6. b4 누르기

일단 누르는건 순서대로 눌러야 하고 그까지 가는 이동은 동시에도 상관없음 이동은 동시에 가능하지만 누르는건 동시불가
이동, 누르기, 가만히 있기
첫번째 눌러야 하는버튼 만큼 시간 더하기
두번째 케이스는 첫번째 케이스 시간 이랑 뺀 절대값에 +1 만큼 시간 더해주기 (첫케이스랑 두번째 케이스의 알파벳이 동일할 경우)
두번째 케이스가 첫번째 케이스와 알파벳 다르면 첫번째 케이스의 숫자보다 작다면 +1만 해주기 / 첫번째 케이스보다 두번째 케이스가 더 크다면 그 차이만큼만 +해주고, -1해주기



스타트는 1이고 여기서 
처음 찍히는 수는 그까지 이동 값에+ 누르는 시간 1해서 
(그까지 수 - 스타트 값 + 누르는시간 1) 이걸 토탈 시간에다가 더하면됨
그 다음 다른 알파벳
1.앞에 값보다 작거나 같으면 그냥 누르는 값+1 
2.앞의 값보다 크면 뒤의 값-앞의 값 더해주기

같은 알파벳
1.앞과 차이를 구하고 거기 +1 를 더해주기

2
1
2

6
'''
'''
T= int(input())
for tc in range(1,T+1):
    commands = list(map(str,input().split()))
    #초반 갯수와 그 뒤에 나오는 것들 나누기 
    first= commands[0]
    others = tuple(commands[1:])
    time =0
    start=1
    if others[0]=="B":
        time+=((int(others[1])-start+1)-1)
        start=int(others[1])
        for idx in range(2,len(others),2):
            if others[idx]=="O":
                if int(others[idx+1]) >start:
                    time+=(int(others[idx+1])-start)
                    start=int(others[idx+1])
                else:
                    time+=1
                    start=int(others[idx+1])
            else:
                time+=(abs(start-int(others[idx+1]))+1)
                start=int(others[idx+1])
    else:
        time+=((int(others[1])-start+1)-1)
        start=int(others[1])
        for idx in range(2,len(others),2):
            if others[idx]=="B":
                if int(others[idx+1]) >start:
                    time+=(int(others[idx+1])-start)
                    start=int(others[idx+1])
                else:
                    time+=1
                    start=int(others[idx+1])
            else:
                time+=(abs(start-int(others[idx+1]))+1)
                start=int(others[idx+1])
    print(f'#{tc} {time}')
    

'''
import sys

# 테스트 케이스 개수를 읽습니다.
T_str = input()
T = int(T_str)

for tc in range(1, T + 1):
    # 입력을 공백 단위로 쪼개서 리스트로 만듭니다.
    line = input().split()
    N = int(line[0])        # 첫 번째 숫자는 버튼 개수
    commands = line[1:]     # 그 뒤부터는 "O 2 B 4..." 순서
    
    # 로봇의 현재 위치 (둘 다 1번에서 시작)
    orange_pos = 1
    blue_pos = 1
    
    # 상대방이 움직이는 동안 내가 얻은 '여유 시간'
    orange_spare = 0
    blue_spare = 0
    
    total_time = 0 # 전체 걸린 시간
    
    # 2개씩 짝지어서 읽습니다 (로봇 이름, 버튼 위치)
    for i in range(0, len(commands), 2):
        robot = commands[i]
        button_loc = int(commands[i+1])
        
        if robot == 'O':
            # 1. 오렌지가 이동해야 할 거리
            dist = abs(button_loc - orange_pos)
            
            # 2. 실제로 걸리는 시간 계산 (거리 - 여유시간)
            # 만약 여유시간이 거리보다 크면 이미 도착한 것이므로 0초
            real_move_time = dist - orange_spare
            if real_move_time < 0:
                real_move_time = 0
                
            # 3. 버튼 누르는 시간 1초를 더함
            time_spent = real_move_time + 1
            
            # 4. 정보 업데이트
            total_time = total_time + time_spent
            orange_pos = button_loc     # 오렌지 위치 이동
            orange_spare = 0            # 오렌지는 방금 버튼 눌렀으니 여유시간 리셋
            blue_spare = blue_spare + time_spent # 블루는 오렌지가 쓴 시간만큼 여유 생김
            
        else: # 블루('B')의 차례일 때 (위와 똑같은 로직)
            dist = abs(button_loc - blue_pos)
            
            real_move_time = dist - blue_spare
            if real_move_time < 0:
                real_move_time = 0
                
            time_spent = real_move_time + 1
            
            total_time = total_time + time_spent
            blue_pos = button_loc
            blue_spare = 0
            orange_spare = orange_spare + time_spent
            
    print(f"#{tc} {total_time}")    
        


'''
T = int(input())
for tc in range(1, T + 1):
    commands = list(map(str, input().split()))
    # N은 첫 번째 값, 나머지는 명령들
    N = int(commands[0])
    others = commands[1:]
    
    # 1. 위치 분리 (기존 start 변수를 두 개로)
    pos_O = 1
    pos_B = 1
    
    # 2. 각 로봇이 마지막으로 버튼을 누른 '시점' 기록
    last_time_O = 0
    last_time_B = 0
    
    total_time = 0 # 전체 흐른 시간
    
    for idx in range(0, len(others), 2):
        robot = others[idx]
        target = int(others[idx+1])
        
        if robot == "O":
            # 이동할 거리 계산
            dist = abs(target - pos_O)
            
            # [핵심] 내가 이동해야 할 시간 계산
            # 전체 시간에서 내가 마지막으로 버튼 누른 시간을 빼면 '내가 자유롭게 이동한 시간'이 나옵니다.
            # (이동 거리 - 자유 이동 시간)과 0 중 큰 값에 버튼 누르는 1초를 더합니다.
            move_needed = max(0, dist - (total_time - last_time_O))
            total_time += (move_needed + 1)
            
            # 정보 갱신
            pos_O = target
            last_time_O = total_time
            
        else: # 블루("B")인 경우
            dist = abs(target - pos_B)
            
            # 오렌지와 똑같은 논리 적용
            move_needed = max(0, dist - (total_time - last_time_B))
            total_time += (move_needed + 1)
            
            # 정보 갱신
            pos_B = target
            last_time_B = total_time
            
    print(f'#{tc} {total_time}')
'''