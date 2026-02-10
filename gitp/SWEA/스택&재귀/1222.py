'''

'''
for tc in range(1,11):
    length = int(input())
    stack=[]
    num = input().strip()
    for idx in range(length):
        if num[idx] !="+":
            stack.append(int(num[idx]))
    

    print(f'#{tc} {sum(stack)}')


