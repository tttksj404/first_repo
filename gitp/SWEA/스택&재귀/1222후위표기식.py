'''


for tc in range(1,11):
    length = int(input())
    stack=[]
    num = input().strip()
    for idx in range(length):
        if num[idx] !="+":
            stack.append(int(num[idx]))
    

    print(f'#{tc} {sum(stack)}')
'''
T = 10
for tc in range(1, T + 1):
    N = int(input())
    infix = input().strip()
    
    # [1단계] 중위 표기식 -> 후위 표기식 변환
    postfix = ""
    stack = []
    
    for char in infix:
        if '0' <= char <= '9':  # 숫자면 바로 출력
            postfix += char
        elif char == '+':       # 연산자면
            # 스택에 있는 +들을 모두 꺼내서 출력 (우선순위가 같으므로 먼저 들어온 게 먼저 나감)
            while stack:
                postfix += stack.pop()
            stack.append(char)  # 그리고 현재 연산자 스택에 저장
            
    # 스택에 남은 연산자 모두 털기
    while stack:
        postfix += stack.pop()
        
    # ---------------------------------------------------
    
    # [2단계] 후위 표기식 계산 (Calculator)
    calc_stack = []
    
    for char in postfix:
        if '0' <= char <= '9':    # 숫자면 스택에 저장 (계산을 위해 int 변환)
            calc_stack.append(int(char))
        elif char == '+':         # 연산자면
            num2 = calc_stack.pop() # 뒤에 들어간 게 num2
            num1 = calc_stack.pop() # 먼저 들어간 게 num1
            calc_stack.append(num1 + num2) # 계산 결과를 다시 스택에
            
    result = calc_stack[0]
    
    print(f'#{tc} {result}')

