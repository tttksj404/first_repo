'''
테스트 개수
만큼 반복
입력받는 케이스 번호 그대로 출력 / 단어의 개수 입력
그 개수만큼 단어 스플릿으로 입력받음 
딕셔너리로 0~9까지 키값으로 zro, one,two 받아주고 value로 0~9까지 

'''

T = input()
for _ in range(int(T)):
    case_num , total_char = map(str, input().split())
    char_list = list(map(str, input().split()))
    case_dict = {"ZRO":"0", "ONE":"1", "TWO":"2","THR":"3","FOR":"4","FIV":"5","SIX":"6","SVN":"7","EGT":"8","NIN":"9"}
    swapped_dict = {v: k for k, v in case_dict.items()} #핵심 딕셔너리의 키와 밸류를 전환시켜주는 식!! 
    case_list = []
    answer_list = []
    for each in char_list:
        case_list.append(case_dict[each])
    case_list.sort() #sort는 문자열밖에 안된다는점 !!!! #또는 숫자 데이터를 .sort(key=int)로 받으면 가능 
    for w in case_list:
        answer_list.append(swapped_dict[w])
    print(f'{case_num}', *answer_list)


'''
import sys

# 표준 입력을 더 빠르게 받기 위함 (선택사항)
input = sys.stdin.readline

T = int(input())

# 기준이 되는 행성 숫자 순서
GNS_ORDER = ["ZRO", "ONE", "TWO", "THR", "FOR", "FIV", "SIX", "SVN", "EGT", "NIN"]

for _ in range(T):
    # #1 7041 형태의 입력을 분리
    case_num, total_count = input().split()
    # 전체 단어 리스트 입력
    words = input().split()

    # 1. 각 단어가 몇 번 나왔는지 저장할 딕셔너리 생성
    count_dict = {word: 0 for word in GNS_ORDER} #처음부터 딕셔너리 설정안하고 몇개를 받는지에 대한 딕셔너리를 나중에 설정하면 
    #기존의 리스트 순서대로 가면서 그 횟수만 적어준걸 바탕으로 뽑기만 하면됨 
    
    # 2. 입력받은 단어들을 순회하며 개수 세기
    for w in words:
        count_dict[w] += 1
    
    # 3. 결과 출력
    print(case_num)
    # GNS_ORDER 순서대로 저장된 개수만큼 반복 출력
    for word in GNS_ORDER:
        # 해당 단어를 개수만큼 반복해서 출력 (공백 포함)
        print((word + " ") * count_dict[word], end="")
    print() # 줄바꿈




'''