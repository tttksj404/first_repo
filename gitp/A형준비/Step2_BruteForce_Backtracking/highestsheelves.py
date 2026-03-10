'''
점원들 키의 합 무조건 B는 넘도록 해야하는데 B 넘는 조건들중 가장 작은 값 찾으면됨
그럼
1) 가지치기- 다 더해도 합이 B 안넘을땐 그냥 return
2) 기저조건- 더하면서 합이 B를 넘을때 + 그중에서 min값
3) for i in range(N)으로 인덱스 찾아가기

total=점원들 키 합
visited=true
dfs(total)
visited=false
'''
def dfs(idx, total):
    global min_total
    if total >= min_total : #종합으로 구한게 최소값보다 크면 어짜피 최솟값 구하라는 의미없기에 가지자르기
        return

    if idx==N: #인덱스가 끝까지 간다면 끝남
        if total>=B:
            min_total=min(min_total,total)
        return

    dfs(idx+1,total+heights[idx])
    dfs(idx+1, total) #건너뛰는 조건도 필요하게됨 이건 부분집합이라서 건너 뛰어서 선택되도 무방하기 때문 









T=int(input())
for tc in range(1,T+1):
    N,B= map(int,input().split())
    heights = list(map(int,input().split()))


    min_total=9999999999999

    dfs(0,0)
    ans = (min_total-B)
    print(f'#{tc} {ans}')
