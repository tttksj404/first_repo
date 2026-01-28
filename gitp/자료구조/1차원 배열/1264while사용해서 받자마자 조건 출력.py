'''
문제
영문 문장을 입력받아 모음의 개수를 세는 프로그램을 작성하시오. 모음은 'a', 'e', 'i', 'o', 'u'이며 대문자 또는 소문자이다.

입력
입력은 여러 개의 테스트 케이스로 이루어져 있으며, 각 줄마다 영어 대소문자, ',', '.', '!', '?', 공백으로 이루어진 문장이 주어진다. 
각 줄은 최대 255글자로 이루어져 있다.

입력의 끝에는 한 줄에 '#' 한 글자만이 주어진다.

출력
각 줄마다 모음의 개수를 세서 출력한다.

예제 입력 1 
How are you today?
Quite well, thank you, how about yourself?
I live at number twenty four.
#

예제 출력 1 
7
14
9
'''


'''

aeiou = ['a','e','i','o','u','A','E','I','O','U']
count = 0

while True: #여기서 while이 #을 input()으로 받기 전까지 반복함 input()만 해서 한줄마다 받음 
    #받으면서 그 안에서 바로 if문으로 조건처리가능 
    text = input()

    if text == '#':
        break
    count = 0
    for every_text in text:
        if every_text in aeiou:
            count+=1
    print(count)

'''
val=['a','e','i','o','u']
sign = '#'
sent = []
sent = list(input())

def func(sent_val):
    count = 0
    for i in sent_val: # input 함수로 받아온 것 조회
        for j in val:
            if i == j: # 이때 input값이랑 모음 리스트 중 하나가 일치한 경우 카운트 증가 !
                while (i==sign):
                    break
                count+=1
    return count
print(func(sent))







    





