'''
T = int(input())
for w in range(1, T+1):
    ah, aw = map(int,input().split())
    checkup = []
    for _ in range(ah):
        apt_list = list(map(int, input().split())))
        for i in apt_list:
            checkup.append(i)
        


    bh, bw = map(int, input().split())
    black_basket = []
    black = 0
    normal = 0
    for _ in range(bh):
        black_list = list(map(int, input().split())))
        for k in black_list:
            black_basket.append(k)

    for a in checkup:
        if a in black_basket:
            black+=1
        else:
            normal+=1

    print(f'{w} {black} {normal}')
            
'''

T = int(input())
for w in range(1, T + 1):
    ah, aw = map(int, input().split())
    checkup = []
    for _ in range(ah):
        # map(int, input().split()) 으로 수정 (콤마 주의!)
        apt_list = list(map(int, input().split()))
        # 하나씩 append 하는 것보다 extend가 훨씬 빠르고 메모리 효율적입니다.
        checkup.extend(apt_list)

    bh, bw = map(int, input().split())
    # [핵심] 리스트 대신 set(집합)을 사용합니다.
    # set은 중복을 제거하고 검색 속도가 미친 듯이 빠릅니다.
    black_basket = set() 
    
    for _ in range(bh):
        black_list = list(map(int, input().split()))
        # set에는 update를 사용하여 한꺼번에 여러 데이터를 넣을 수 있습니다.
        black_basket.update(black_list)

    black = 0
    normal = 0

    # 이제 이 루프는 데이터가 아무리 많아도 눈 깜빡할 새에 끝납니다.
    for a in checkup:
        if a in black_basket: # set에서의 탐색은 순식간에 끝납니다.
            black += 1
        else:
            normal += 1

    print(f'#{w} {black} {normal}')

    '''

import sys
sys.stdin = open("input.txt", "r")

T = int(input())

for tc in range(1, T + 1):
    h, w = map(int, input().split())
    apart = [list(map(int, input().split())) for _ in range(h)]
    bh, bw = map(int, input().split())                                 #미리 값을 전부 받고 나서 생각하고 들어가도 괜찮음 !!!
    blacklist = [list(map(int, input().split())) for _ in range(bh)]   #변수 지정해줬으므로 변수지정해서 부터는 순서는 상관없어짐

    # [주의] 100,000번 까지 가능 -> 100,001 개 만들어주어야한다
    is_blacklist = [0] * 100001

    # 블랙리스트 숫자를 하나씩 보면서, 블랙리스트 체크
    for row in blacklist:
        for num in row:
            is_blacklist[num] = 1

    # 아파트를 보면서, 블랙리스트가 몇 명인지 센다.
    blacklist_cnt = 0
    for row in apart:
        for num in row:
            # 만약 체크되어있다면 블랙리스트 카운트 추가
            if is_blacklist[num]:
                blacklist_cnt += 1

    print(f'#{tc} {blacklist_cnt} {h * w - blacklist_cnt}')
    '''