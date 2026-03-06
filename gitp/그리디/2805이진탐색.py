N,M =map(int,input().split())
woods = list(map(int,input().split()))

#정석 이진탐색
 #left는 woods의 min값 / right는 woods의 max값 
    #target은 각 리스트의 값을 뺐을때 값이 M이 나와야함 
left=0
right=2000000000

while left<right:
    mid = (left+right)//2
    total = 0
    for wood in woods:
        total += max(wood-mid, 0) #자른것 보다 큰 나무만 가져간다는거 / 자른 것 보다 작은 나무라서 음수뜨면 오히려 0커서 그냥 상관x 
    if total<M:
        right=mid
    else:
        left=mid+1
print(left-1)









