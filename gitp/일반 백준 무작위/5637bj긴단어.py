'''
문제
단어는 알파벳(a-z, A-Z)과 하이픈(-)으로만 이루어져 있다. 단어와 다른 문자(마침표, 숫자, 심볼, 등등등...)로 이루어진 글이 주어졌을 때, 
가장 긴 단어를 구하는 프로그램을 작성하시오.

Apple의 길이는 5, son-in-law는 10, ACM-ICPC는 8이다.

입력
입력은 여러 줄, 문단으로 이루어져 있다. 하지만, 10,000글자를 넘지 않는다. 단어의 길이는 100을 넘지 않는다. E-N-D는 입력의 마지막을 의미한다.

출력
가장 긴 단어를 소문자로 출력한다. 가장 긴 단어가 여러개인 경우에는 글에서 가장 먼저 나오는 것을 출력한다.

예제 입력 1 
  ACM International Collegiate Programming Contest (abbreviated as 
ACM-ICPC or just ICPC) is an annual multi-tiered computer programming 
competition among the universities of the world. The contest is 
sponsored by IBM. Headquartered at Baylor University, with autonomous 
regions on six continents, the ICPC is directed by Baylor Professor 
William B. Poucher, Executive Director, and operates under the 
auspices of the Association for Computing Machinery (ACM). 

  The 2012 ACM-ICPC Asia Hatyai Regional Programming Contest is 
held during 15-16 November 2012. It is hosted by Prince of Songkla 
University, Hatyai campus. E-N-D

예제 출력 1 
international
'''

'''
letter = list(map(str, input().split()))

def get_length(word):  #이 메커니즘 가장 중요 / 글자를 세는 메커니즘 최소 최대도 마찬가지로 일단 함수 값 설정후 +=1로 하거나 그 함수값 계속 변환
    count = 0
    for _ in word:
        count +=1
    return count

max_len = 0
for words in letter:
    current_len = get_length(words)
    if current_len > max_len:
        max_len = current_len
print(max_len)
'''



max_len = 0
longest_word = ""

while True:
    try:
        # 1. 한 줄을 입력받아 단어 리스트로 만듭니다.
        line = input().split()
        
        # 만약 빈 줄이 입력되면 다음 줄로 넘어갑니다.
        if not line:
            continue
            
        for word in line:
            # 2. 종료 조건 확인
            if word == 'E-N-D':
                print(longest_word.lower()) # 최종 우승 단어 출력
                exit() # 프로그램 완전히 종료

            # 3. 단어 정제 (알파벳과 하이픈만 골라내기)
            pure_word = ""
            current_len = 0
            for char in word:
                if 'a' <= char <= 'z' or 'A' <= char <= 'Z' or char == '-':
                    pure_word += char
                    current_len += 1
            
            # 4. 최대 길이 비교 및 단어 저장
            if current_len > max_len:
                max_len = current_len
                longest_word = pure_word
                
    except EOFError: # 더 이상 입력할 내용이 없을 때 안전하게 종료
        break




