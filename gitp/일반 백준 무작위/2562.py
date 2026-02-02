import sys

# 입력된 모든 값을 공백/줄바꿈 기준으로 잘라서 리스트로 만듭니다.
my_list = list(map(int, sys.stdin.read().split()))
a= max(my_list)
print(a)
print(my_list.index(a)+1) #인덱스는 0부터 시작한다는거 고려해서 몇번째 수인지 알려면 인덱스에서 +1해줘야함

