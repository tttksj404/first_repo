T = int(input())
for w in range(1, T+1):
    stick = input().strip()
    pieces = 0 
    stick_count = 0 
    for idx in range(len(stick)):
        if stick[idx] == "(":
            stick_count+=1
        else: 
            stick_count-=1
            if stick[idx-1] == "(": 
                pieces += stick_count 
            else: 
                pieces +=1
    print(f'#{w} {pieces}')