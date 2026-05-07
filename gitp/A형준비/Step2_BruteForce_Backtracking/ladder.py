'''
그냥 visited a1,b1에 한다음에
a<=b 이면 a부터 b까지 visited
a>b 이면 b부터 a까지 visited
만약에 이미 visited 되어있는 곳이면 total+=1씩

'''
T= int(input())
for tc in range(1,T+1):
    N=int(input())
    total=0
    wires=[list(map(int,input().split())) for _ in range(N)]

    for i in range(N):
        for j in range(i+1,N):
            a1,b1=wires[i]

            a2,b2=wires[j]

            if (a1<a2 and b1>b2) or (a1>a2 and b1<b2):
                total+=1
    print(f'#{tc} {total}')

