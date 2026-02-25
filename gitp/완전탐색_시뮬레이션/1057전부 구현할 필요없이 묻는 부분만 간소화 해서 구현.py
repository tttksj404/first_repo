N,kim,lim= map(int,input().split())
if N%2==0:
    count=1
    kim=(kim+1)//2
    lim=(lim+1)//2
    if kim==lim:
        print(count)
    else:
        while kim!=lim:
            kim=(kim+1)//2
            lim=(lim+1)//2
            count+=1
            if kim==lim:
                print(count)
                break
else:
    if kim==N or lim==N:
        count= (N//2)+1
        print(count)
    else:
        while kim!=lim:
            kim=(kim+1)//2
            lim=(lim+1)//2
            count+=1
            if kim==lim:
                print(count)
                break

'''
N, kim, lim = map(int, input().split())

count = 0

# 두 사람의 번호가 같아질 때까지 반복합니다.
# 번호가 같아진다는 것은 "해당 라운드에서 서로 대결한다"는 뜻입니다.
while kim != lim:
    # 다음 라운드 번호 부여: (현재번호 + 1) // 2
    # 이 식 하나로 홀수/짝수 번호가 모두 올바른 다음 번호를 받게 됩니다.
    kim = (kim + 1) // 2
    lim = (lim + 1) // 2
    
    # 한 라운드 진행
    count += 1

print(count)        
'''

