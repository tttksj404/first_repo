T = int(input())
for w in range(1,T+1):
    fstr = input().strip()#문자열은 항상 strip으로 받기 
    sstr = input().strip()
    count_dict = {char: 0 for char in fstr} #컴프리헨션으로 일단 기본값 fstr로 키 다 받기 
    for s in sstr:
        if s in fstr:
            count_dict[s]+=1
    
    print(f'#{w} {max(count_dict.values())}')
'''
3
XYPV
EOGGXYPVSY
STJJ
HOFSTJPVPP
ZYJZXZTIBSDG
TTXGZYJZXZTIBSDGWQLW
'''