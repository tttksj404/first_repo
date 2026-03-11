# 이진탐색을 두번 써야하는이유는 우리가 찾고자 하는게 하나의 점이 아니고 범위의 양 끝단이기 때문이다
#오른쪽 끝단 - 왼쪽 끝단이 -> 그 사이의 개수를 나타내기 때문 

T=int(input())
for tc in range(1,T+1):
    N,Q = map(int,input().split())

    coral = list(map(int,input().split()))
    coral.sort() #반드시 정렬 써줘야함 어짜피 left로 그 개수나 위치 구할텐데 그럴려면 정렬되어 있어야하기 때문
    storage=[]

    for ind in range(Q):
        q1,q2=map(int,input().split())

        left=0
        right=N
        while left<right:
            mid = (left+right)//2

            if coral[mid]<q1: #지금 찾는 값=mid 니까 이게 이조건 만족해야만 오른쪽으로 몇개 있나 확인하러감 left=mid+1 이니까 mid값이 하나씩 뒤로
                #정렬된 순간에서 지금 q1이상의 초반 left값을 찾는건데 이 값이 q1보다 작다는건 이상인걸 찾으려면 오른쪽으로 left를 더 봐야한다는거
                left=mid+1
            else:              #여긴 q1을 만나거나 그거보다 크면 큰건 알겠는데 큰것중 최소의 값은 뭘까를 찾으려 한다는거
                right=mid
        start=left

        left=0
        right=N
        while left<right:
            mid = (left+right)//2

            if coral[mid]<=q2: #여긴 애초에 q2보다 작거나 같은걸 찾아야하는데 여기에 만족하면 q2보다 작은것중 오른쪽으로 최대값을 찾아야 범위 정할 수 있어서 
                left=mid+1
            else:        #q2보다 크면 지금 q2보다 작거나 같은걸 찾으니 오른쪽으로 부터 왼쪽으로 작은걸 탐색해서 q2에 근접하는 가장 작은 끝값 찾는거
                right=mid
        end=left

        storage.append(end-start)

    print(f'#{tc}',*storage)
        