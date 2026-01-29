#일단 기다림의 값 같은 문자열 있는 곳 +10 해주기 해당 문자열에서 
#문자열 몇번 눌러야 하는지에 따라서 유니코드 가져와서 알아서 노가다후 같은 문자열 리스트로 묶어주기 
#한번 누를때 마다 *2씩 해주는데 그 문자열이 몇번 눌러야하는지에 따라 그x값에 *2하면됨


p,w = map(int, input().split()) #p는 누를때 마다 걸리는 시간 / #w는 연속위해 걸리는 시간

sentence = list(input())

dict= {1:['A','D','G','J','M','P','T','W'], 2:['B','E','H','K','N','Q','U','X'],3:['C','F','I','L','O','R','V','Y'],4:['S','Z']}
number_book = {2:['A','B','C'], 3:['D','E','F'],4:['G','H','I'],5:['J','K','L'],6:['M','N','O'],7:['P','Q','R','S'],8:['T','U','V'],9:['W','X','Y','Z']}

press_count =0
loading_count = 0

for char in sentence:
    if char in dict[1]:
        press_count += 1*p
    elif char in dict[2]:
        press_count += 2*p
    elif char in dict[3]:
        press_count+= 3*p
    elif char == ' ':
        press_count += 1*p
    elif char in dict[4]:
        press_count += 4*p

for ind in range(len(sentence)-1):   #and 하기전에 in을 앞뒤로 2번 받아줘야 한다
    if sentence[ind] in number_book[2] and sentence[ind+1] in number_book[2]:
        loading_count +=w
    elif sentence[ind] in number_book[3] and sentence[ind+1] in number_book[3]:
        loading_count +=w
    elif sentence[ind] in number_book[4] and sentence[ind+1] in number_book[4]:
        loading_count +=w
    elif sentence[ind]in number_book[5] and sentence[ind+1] in number_book[5]:
        loading_count +=w
    elif sentence[ind] in number_book[6]and sentence[ind+1] in number_book[6]:
        loading_count +=w
    elif sentence[ind]in number_book[7] and sentence[ind+1] in number_book[7]:
        loading_count +=w
    elif sentence[ind]in number_book[8] and sentence[ind+1] in number_book[8]:
        loading_count +=w
    elif sentence[ind]in number_book[9] and sentence[ind+1] in number_book[9]:
        loading_count +=w

answer = press_count + loading_count
print(answer)


#아래에는 최적화 방법

'''
import string

# 1. 버튼별 알파벳 그룹화 (2번 버튼부터 9번 버튼까지 순서대로)
groups = ["ABC", "DEF", "GHI", "JKL", "MNO", "PQRS", "TUV", "WXYZ"]

# 2. 통합 정보를 담을 딕셔너리
info = {}

# 3. 이중 루프로 자동 생성
for i, group in enumerate(groups, start=2):  # i는 버튼 번호 (2, 3, 4...)
    for j, char in enumerate(group, start=1): # j는 누르는 횟수 (1, 2, 3...)
        info[char] = (i, j)  # 예: info['A'] = (2, 1)

# 4. 공백 예외 추가 (1번 버튼, 1번 누름)
info[' '] = (1, 1)


total_time = 0
prev_btn = None

for char in sentence:
    btn, press = info[char] # (버튼 번호, 누름 횟수)를 한 번에 가져옴
    
    # 1. 누르는 시간 더하기
    total_time += (press * p)
    
    # 2. 대기 시간 체크 (같은 버튼이면서 공백이 아닐 때)
    if prev_btn == btn and btn != 1:
        total_time += w
    
    prev_btn = btn



'''