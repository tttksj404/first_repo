#그냥 v자형 탐색
#왼쪽에서 오른쪽으로 탐색 가장 높은 peak을 찾아가며 찾으면 그다음 peak을 찾기전까지 넓이


import sys

# 1. 입력 받기
n = int(sys.stdin.readline())
pillars = []   # 기둥 담아둘 리스트 
max_h = 0      # 가장 높은 기둥의 높이
max_idx = 0    # 가장 높은 기둥의 위치


# 기둥 정보를 받고, 가장 높은 기둥의 정보를 미리 파악합니다.
heights = [0] * 1001 # L의 범위가 1~1000이므로 #방 범위를 만드는 것 뿐 
end_point = 0 #끝 범위 알아야 reversed로 range해서 범위 설정가능함 

for _ in range(n): #n만큼 반복해서 
    l, h = map(int, sys.stdin.readline().split()) #기둥개수만큼 기둥의 넓이와 길이 받음
    heights[l] = h #일단 지금의 높이 설정을 h로 해줌 
    if h > max_h: #그리고 그 값이 max_h라는 최대 높이보다 크면 
        max_h = h #그걸 최대 높이값으로 
        max_idx = l #그리고 그 최대 높이값이 있는 인덱스를 l로 
    if l > end_point: #끝 값이 l이 end_point보다 크면 l이 end_point가 됨
        end_point = l

total_area = 0 #구해야하는 넓이 0으로 초기화
current_height = 0 #지금의 높이도 0으로 초기화

for i in range(max_idx+1):  #max_idx까지 반복   #일단 내가 지금 위치 i 에 서있고 heights[i]는 내 앞의 기둥
    current_height = max(current_height, heights[i]) #최대 길이라고 할 것은 현재 길이랑, 그다음 길이중에 가장 큰 길이를 구해서 그걸
                                                     #그게 넓이 자체니까 넓이에다가 넣어주기 그래프 길이는 항상 1이니까 
    total_area += current_height

current_height = 0 #current_height 초기화 
for i in range(end_point, max_idx,-1): #역으로 돌아가서 max_idx +1 부터 시작 해서 end_point 전까지 반복  #STAR값은 포함 / END값에는 그것보다+1 (-1STEP이라면)
    #STEP이 1이라면 END는 그 값 미만 즉 END-1까지만 
    current_height = max(current_height, heights[i])
    total_area += current_height

print(total_area)