'''
문제
숫자 카드는 정수 하나가 적혀져 있는 카드이다. 상근이는 숫자 카드 N개를 가지고 있다. 정수 M개가 주어졌을 때, 
이 수가 적혀있는 숫자 카드를 상근이가 몇 개 가지고 있는지 구하는 프로그램을 작성하시오.

입력
첫째 줄에 상근이가 가지고 있는 숫자 카드의 개수 N(1 ≤ N ≤ 500,000)이 주어진다. 둘째 줄에는 숫자 카드에 적혀있는 정수가 주어진다.
 숫자 카드에 적혀있는 수는 -10,000,000보다 크거나 같고, 10,000,000보다 작거나 같다.

셋째 줄에는 M(1 ≤ M ≤ 500,000)이 주어진다. 넷째 줄에는 상근이가 몇 개 가지고 있는 숫자 카드인지 구해야 할 M개의 정수가 주어지며, 
이 수는 공백으로 구분되어져 있다. 이 수도 -10,000,000보다 크거나 같고, 10,000,000보다 작거나 같다.

출력
첫째 줄에 입력으로 주어진 M개의 수에 대해서, 각 수가 적힌 숫자 카드를 상근이가 몇 개 가지고 있는지를 공백으로 구분해 출력한다.

예제 입력 1 
10
6 3 2 10 10 10 -10 -10 7 3
8
10 9 -5 2 3 4 5 -10

예제 출력 1 
3 0 0 1 2 0 0 2
'''

N = int(input()) #가지고 있는 카드 개수
total_card_number = list(map(int, input().split())) #뽑을 전체 카드 
M = int(input()) #뽑을 카드 개수 
pick_card_number = list(map(int, input().split())) #뽑힌카드 

answer_dict = {} #키와 벨류로 해당되는 숫자와 그 개수를 담을 딕셔너리 
#answer_dict.keys() == pick_card_number  #일단 내가 뽑을 숫자 리스트 전체를 key에 이식 
#answer_dict.values() == 0 #숫자 셀 준비위해 0초기화 
# answer_dict = dict.fromkeys(pick_card_number, 0) 매우중요한 방식


'''
for ind in range(len(pick_card_number)):
    if pick_card_number[ind] in total_card_number:
        real_ind = pick_card_number[ind]
        answer_dict[real_ind] +=1 
        
for number in total_card_number:
    if number in pick_card_number:  # 역발상으로 for문 돌려도 됨  그래서 막히면 일단 for는 큰값 및 중복값 존재하는 곳에서 뽑는것으로 역발상생각 
        answer_dict[number] +=1
'''
for number in total_card_number:   
    '''
    answer_dict = {}라는 장부 만들고 거기다가 존재하는 모든 카드를 하나씩 넣어서 그 키값에 value를 +=1해줌
    장부에 없었다면 그 값(value)을 1추가를 해주고, 그 다음부터 1씩 추가해주는 식으로 진행 그래서 초반에 total_card_number안에 숫자 하나씩 answer_dict에 
    key값으로 전부 들어가는데 중복되는 key가 있다면 +=1씩 value를 높여주게됨 


    '''
    if number in answer_dict:
        answer_dict[number] +=1
    else:
        answer_dict[number] =1
'''
여기서는 뽑아야하는 카드숫자를 뽑고 그게 answer_dict에 있다면 새로운 장부로 만든 result 리스트에 answer_dict의 key의 value값을 append해서 넣어줌
만약 그게 answer_dict에 없으면 그냥 0넣어서 그 자리에 없다는거 표시해주기 
그렇게 리스트안에 pick_card_number의 자리수만큼 value값이 그대로 들어가게됨 [3,0,0,1,2,0,0,2]이런식 거기에다가 *을 앞에 붙이면 리스트 벗겨지며 
뛰어쓰기로 구분되어짐 

'''
result = []
for pick in pick_card_number:
    if pick in answer_dict:
        result.append(answer_dict[pick]) 
    else:
        result.append(0)
print(*result)
        






'''
출력 그대로 문제 그대로 만들어 놓기
N = int(input())
nums1 = list(map(int,input().split())) #숫자 공백에 사용
M = int(input())
nums2 = list(map(int,input().split()))

#countting dict초기화
di= {}
for num in nums1:
    if di.get(num):
        di[num]+=1
    else:
        di[num] = 1

#countting 수 출력 해주는 것
for num2 in nums2:
    if di.get(num):
        print(di[num], end='')
    else:
        print(0, end='')
--------------------------------------------------------------------------------------------------------------------------------------



시간 제한 1초 
->1초안에 들어갈 수 있는 코드는 어떤 게 있을까? 

N: 500,000
M: 500,000
2중 for 문 일 경우 
->시간 복잡도에서 쓰면 안되겠다는 것을 미리 캐치하기 / 나중에 시간제한 , 메모리 제한에서 보고 판단이 서야함 / 알고리즘 쓰면된다 안된다로
->자료구조와 알고리즘 선택시 검증 

-> 코딩테스트는 알고 있는 것중 뭘쓸지 고르는게 어렵기에 미리 시간복잡도로 거를 수 있음 





'''