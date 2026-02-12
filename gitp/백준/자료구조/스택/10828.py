import sys
command_num = int(input())
stack = []
last_ind = len(stack)-1
for n in range(command_num):
    

# 반복문 안에서
    command = sys.stdin.readline().split()
    if command[0] == "push":
        value = int(command[1])
        stack.append(value)
    elif command[0] == "pop":
        if stack == []:
            print(-1)
        else:   
            print(stack.pop())
    elif command[0] == "size":
        len(stack) #여기서 len 을 써야지 count는 특정 문자나 숫자의 개수 구하는거
        #len으로 전체 리스트안의 개수를 구하는거지 
        #count는 특정 문자나 숫자 개수만
        print(len(stack))
    elif command[0] == "empty":
        if stack == []:
            print(1)
        else:
            print(0)
    elif command[0] == "top":
        if stack == []:
            print(-1)
        else:   
            print(stack[last_ind])









# 1. 'push 10'을 입력했을 때
# command는 ['push', '10'] 이 됩니다.

# 2. 'top'을 입력했을 때
# command는 ['top'] 이 됩니다.