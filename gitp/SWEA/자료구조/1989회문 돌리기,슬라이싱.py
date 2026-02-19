'''
T = int(input())
for w in range(1,T+1):
    word = input()
    word_t = reversed(word)
    if word == word_t:
        print(f'{w} 1')
    else:
        print(f'{w} 0')
'''

T = int(input())
for w in range(1, T+1):
    word = input().strip()
    first=[]
    second = []
    for a in range(len(word)):
        first.append(word[a])
    for b in range(len(word)-1,-1,-1):
        second.append(word[b])
    if first == second:
        print(f'#{w} 1')
    else:
        print(f'#{w} 0')

    
# 아니면 if word == word[::-1]슬라이싱으로 역으로 돌릴 수 있음 
