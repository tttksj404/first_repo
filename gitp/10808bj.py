'''
문제
알파벳 소문자로만 이루어진 단어 S가 주어진다. 각 알파벳이 단어에 몇 개가 포함되어 있는지 구하는 프로그램을 작성하시오.

입력
첫째 줄에 단어 S가 주어진다. 단어의 길이는 100을 넘지 않으며, 알파벳 소문자로만 이루어져 있다.

출력
단어에 포함되어 있는 a의 개수, b의 개수, …, z의 개수를 공백으로 구분해서 출력한다.

예제 입력 1 
baekjoon
예제 출력 1 
1 1 0 0 1 0 0 0 0 1 1 0 0 1 2 0 0 0 0 0 0 0 0 0 0 0
'''

S = list(map(str, input())) #입력된 값은 리스트 형태로 받아짐 거기서 인덱싱으로 각 단어 하나하나 구분 

alphabet = {'a': 0,'b':0,'c':0,'d':0,'e':0,'f':0,'g':0,'h':0,'i':0,'j':0,'k':0,'l':0,'m':0,'n':0,'o':0,'p':0,'q':0,'r':0,'s':0,'t':0,'u':0,'v':0,'w':0,'x':0,'y':0,'z':0}
all_keys= alphabet.keys()
ind = 0
for ind in range(len(S)):
    if S[ind] in all_keys:
        key=S[ind]  #여기서 딕셔너리 key값이랑 리스트의 인덱스 값 헷갈리지 않기 !!! 
        alphabet[key]+=1  #연산자는 반드시 +=1을 붙여줘야 해결된다 

print(*alphabet.values())   # 앞에 *붙여서 애스터 리스크 활용하면 하나씩 꺼내서 보여줌 



'''
1.리스트로도 해당 문제를 풀 수 있음
    dat로 풀이가능 

count_list = [0]*26  #1차원 배열  


for w in S:
    count_list[ord(w)-ord('a')]+=1  #1대1  대응시켜놨다고 생각하고 바로 풀이한다는 것 
                                    #대신 카운트 하는 범위가 작을 때 사용하기가 쉬움 
                                    #count_list[0] +=1 #0=a라고 가정
                                    #count_list[1] +=1 #1=b라고 가정
                                    #이걸 DirectAddressTable=dat 라고 함 인덱스에 나만의 의미를 부여해서 활용하는 방법
print(*count_list) *을 붙이면 언패킹 한다는 소리 





set은 중복제거임 (a가 몇번들어오고 이런건 가능) but 순서대로 출력인데 애초에 불가능

2.정석대로는 
    딕셔너리로 풀이가능

S = input()
di = {}

for w in range(ord('a'),ord('z')+1):
    print(chr(w))
    #이러면 알파벳으로 출력 그러나 그냥w 하면 알파벳의 숫자값들 반환

for w in range(ord('a'),ord('z')+1):
    di[chr(w)] = 0

for w in S:
    di[w] +=1

for v in di.values():
    print(v, end=' ')

이걸 defaultdict로 쉽게 풀이가능

from collections import defaultdict
S = input()
di = defaultdict(int) #없는 키는 자동으로 0으로 초기화

for w in S:
    di[w]+=1 

for w in range(ord('a'),ord('z')+1):
    print(di[chr(w)], end'')
'''
