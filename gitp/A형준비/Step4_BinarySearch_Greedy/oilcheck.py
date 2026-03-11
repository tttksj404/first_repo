T= int(input())
for tc in range(1,T+1):
    check = list(map(str,input().strip()))

    left = 0
    right = len(check) #->이걸 포함되지 않는 끝 경계선으로 보기 때문 리스트의 마지막 인덱스보다 1큰 값이 경계선이됨 
    

    while left<right:
        mid = (right+left)//2

        if check[mid]=="_":
            right=mid
        else:
            #total+=1 #토탈을 하게 되면 데이터의 개수가 아닌 탐색을 수행한 횟수를 세게 됨 
            left=mid+1
    print(f'#{tc} {int(left*100/len(check))}%') #대신 left는 #의 개수가 있으면 하나씩 추가하므로 가능
    #print(total) #-> 이건 왜 안되냐? 