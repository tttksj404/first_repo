def fly_catcher(case,y,x):
    for a in range(y-1,y+2):
        case.append(numbers[a][x])
    for b in range(x-1,x+2):
        case.append(numbers[y][b])
    case.remove(numbers[y][x])
    return sum(case)
    

    


T = int(input())
for w in range(1,T+1):
    N = int(input())
    for i in range(N): #행 만큼 반복 
        numbers = list(map(int, input().split()))
    storage = []
    max_killer = max(storage)
    for r in range(N):
        if r>=1 and r<=N-1:
            for c in range(N):
                 if c>=1 and c<=N-1:
                      if fly_catcher(storage,r,c) == max_killer:
                          pass
                          
                      

    

