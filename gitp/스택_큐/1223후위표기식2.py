'''
stack = [0]*10
top = -1

icp = {'(':3,'*':2, '/':2, '+':1,'-':1}#스택 밖에서 우선순위
isp = {'(':0,'*':2, '/':2, '+':1,'-':1}#스택 안에서 우선순위

infix =  #중위식 문자열
postfix = '' #후위식 문자열

for token in infix:
    if token not in '(*/+-)': #피연산자면 후위식에 추가
        postfix+= token
    elif token ==')': #닫는 괄호면 여는 만나야함
        while top >-1 and stack[top]!= '(':
            top -=1
            postfix += stack[top+1]
        #while stack and stack[-1] != '(':
        #    postfix+=stack.pop()
        if top != -1:
            top -=1 #'(' 제거 
    else: #사칙 연산자인 경우 '(*/+-'인경우
        if top == -1 or isp[stack[top]] < icp[token]:
            top +=1
            stack[top] = token
        elif isp[stack[top]] >= icp[token]:
            while top >-1 and isp[stack[top]] >= icp[token]:
                top -= 1
                postfix +=stack[top+1]
            top+=1 #스택의 마지막 연산자보다 
            stack[top]= token #우선순위가 높아졌으므로 push

    
while top >-1:
    top -=1
    postfix = stack[top+1]
print(postfix)
'''





# 연산자 우선순위 설정
# icp(in-coming priority): 스택에 들어갈 때의 우선순위
# isp(in-stack priority): 스택 안에 있을 때의 우선순위
prec = {'*': 3, '/': 3,'+': 2, '-': 2,'(': 1 }

T = 10
for tc in range(1, T + 1):
    N = int(input())
    infix = input().strip()
    
    # [1단계] 중위 표기식 -> 후위 표기식 변환
    postfix = []
    stack = []
    
    for char in infix:
        if '0' <= char <= '9':  # 피연산자(숫자)
            postfix.append(char)
        elif char == '(':       # 여는 괄호는 일단 스택에 push
            stack.append(char)
        elif char == ')':       # 닫는 괄호를 만나면
            while stack and stack[-1] != '(': # 여는 괄호를 만날 때까지 pop
                postfix.append(stack.pop())
            stack.pop()         # '(' 자체를 스택에서 제거
        else:                   # 연산자 (+, -, *, /)
            # 현재 연산자보다 우선순위가 높거나 같은 것들은 모두 pop하여 결과에 추가
            while stack and stack[-1] != '(' and prec[stack[-1]] >= prec[char]:
                postfix.append(stack.pop())
            stack.append(char)
            
    while stack: # 스택에 남은 것 처리
        postfix.append(stack.pop())
        
    # ---------------------------------------------------
    
    # [2단계] 후위 표기식 계산
    calc_stack = []
    
    for char in postfix:
        if '0' <= char <= '9':
            calc_stack.append(int(char))
        else:
            # 연산자를 만나면 피연산자 두 개를 꺼냄 (순서 주의!)
            num2 = calc_stack.pop()
            num1 = calc_stack.pop()
            
            if char == '+': calc_stack.append(num1 + num2)
            elif char == '-': calc_stack.append(num1 - num2)
            elif char == '*': calc_stack.append(num1 * num2)
            elif char == '/': calc_stack.append(num1 // num2) # 정수 나눗셈
            
    print(f'#{tc} {calc_stack[0]}')