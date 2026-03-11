'''
// 해서 나오는 값이 나오는 조각이됨 
'''

T=int(input())
for tc in range(1,T+1):
    N,K=map(int,input().split())
    storage=[]
    for _ in range(N):
        a= int(input())
        storage.append(a)
    
    left=1 #자르는 길이 mid값은 1부터 츄로스들의 길이의 최대값 에서 고름 그걸 고르면 츄로스 몇개 나오는지 알 수 있기에
    right=max(storage)

    while left<=right: #최적의 길이 left,right 교차할때까지 검사 
        mid=(left+right)//2  #(mid 값 // storage속 각값 )->이거 전부 total에 더했을때 k개 안나오면 
        #mid 값 수정 들어가야함 total이 k값 보다 크면 오른쪽에서 좁혀오고/ k값보다 작으면 왼쪽에서 더해오고
        if mid ==0:
            break

        total=0
        for each in storage:
            total+=each//mid
        
        if total>=K: #K개 이상 만들어지면 성공 #k랑 같아도 되지만 넘어도 상관은 없음 k개 이상이니까 문제 잘보고 조건 
            ans=mid #일단 현재 길이 저장
            left = mid+1
        
        else:
            right=mid-1
    
    print(f"#{tc} {ans}")



