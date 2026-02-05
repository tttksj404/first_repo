'''
T =int(input())
for w in range(1,T+1):

N은 조명의수
pattern = list(map(int,input().split()))
default = [0]*N 
count = 0
m번쨰 조명 클릭시 m배수 조명이 전부 영향받음
pattern의 1의 위치 인덱스로 전부 받아서 적어놓기
pattern에서 초반 1의 위치를 찾아 default에서 거기의 배수 까지 전부 1더해주고 count+=1
그다음 1의 위치 찾아 그 위치의 배수 전부 1 
다음 1위치 배수 전부 1
그 상태에서 이미 1이면 넘어가는 조건식 필요

다음 for 문으로 1의 인덱스 넣은거 돌리는데 default[]값에서 1안나오면 그인덱스 1전환해주고 count+=1
그렇게 끝까지 돌려서 1나오는지 확인 

print 하면됨



'''