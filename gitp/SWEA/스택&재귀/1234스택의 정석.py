'''
처음에는 바로 옆 숫자 같은 거 찾기
1,3,5...순서대로 옆 숫자 비교후 같으면 날려버리기 try, except ?
더이상 비슷하지 않으면 새롭게 바로 옆 숫자가 같은 거 찾기
이거 반복해서 
더 이상 바로 옆 숫자가 같지 않으면 남은 숫자들 출력
count는 없어진 숫자 개수 세기 한번없어지면 
2개씩 없어지니까 n*2

'''
'''
def delete(problem_list):
    clear_list=[]
    for s in range(len(problem_list)-1):
        if problem_list[s] ==problem_list[s+1]:
            start = s #줄인다음 길이 계산해서 다시 start 배정
            for n in range(len(problem_list)-s):
                try:
                    if problem_list[s-n] == problem_list[s+2*n+1]:
                        clear_list.append(s-n)
                        clear_list.append(s+2*n+1)
                
'''
#start 인덱스로 계속 돌아와서 그다음 인덱스 값이랑 비교하는 재귀 함수
#어짜피 1,2,3,4,4,3 일때 4에서 start하면 44없애고 1,2,3,3 이렇게 되니까 다시 start 3으로 바뀌꼬
#다시 1,2,3,3에서 바로 옆 숫자랑 비교후 없애고 start -=1 만 하면 새로운 시작점
'''
def delete(start_idx, num_list):
    while True:
        try:
            if num_list[start_idx]==num_list[start_idx+1]:
                num_list.pop(start_idx)
                num_list.pop(start_idx)
                return delete(start_idx-1, num_list)


        except:
            return num_list
        
for w in range(1,11):
    start = 0
    N, password = map(int, input().split())
    password = list(map(int, str(password)))
    for a in range(N-1):
        if password[a]==password[a+1]:
            start = a
            print(f'#{w} {delete(a,password)}')
'''


#더 간단하게 그냥 스택에다가 쌓아놓고 pop으로 뽑아서 제거 스택에 방금 이전에 들어간 문자와
#방금 들어간 문자를 비교해서 같으면 지금 넣으려는 문자도 안넣고 스택에서 그 문자도 제거해버리기
#그렇게 쌓은 스택에는 같지 않은 수만 들어가기에 결국 스택안의 수는 답이됨


for w in range(1,11):
    N, password = input().split()
    stack = [] #스택만들고 거기다가 넣어서 1대1비교후 pop으로 제거 

    for char in password:
        if stack and stack[-1] == char: #지금 넣으려는 글자와 이미 이전에 들어간 글자 비교 
            stack.pop() #같다면 스택에 넣으려는거 안넣고 이전에 들어간 글자는 pop으로 제거 
        else:
            stack.append(char)

    print(f'#{w} {"".join(stack)}')




        






