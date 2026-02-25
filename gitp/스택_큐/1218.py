'''
딕셔너리로 (), [], {},<> 전부 묶어주기 
스택에다가 넣고 비교해서 찾는거 없으면 넣기 있으면 pop 



'''
'''
for tc in range(1,11):
    chr_len = int(input())
    char = list(input().strip())
    answer_dict={"(":")","[":"]","{":"}","<":">"}    
    for ind in range(chr_len): #"(" 가 c라고 하고
        for idx in range(chr_len): #")" 가 i라고 하면 
            if char[idx]== answer_dict[char[ind]]:
                char[idx], char[ind]="0","0"
            elif char[idx] not in answer_dict[char[ind]]:
                print(f'#{tc} 0')
                break
    char.remove("0")
    if chr_len ==0:
        print(f'#{tc} 1')
'''
for tc in range(1,11):
    chr_len = int(input())
    char = list(input().strip())
    stack = []
    answer_dict={")":"(","]":"[","}":"{",">":"<"}
    answer = 1

    for chr in char:
        if chr not in answer_dict:
            stack.append(chr) #스택에는 전부 여는 가로 존재 
        else: #만약 닫는 가로 아니고 여는 가로가 chr이라면
            if not stack or stack[-1] != answer_dict[chr]:#스택이 비워졌거나, 스택전에 값이 딕셔너리 벨류값에 없다면
                answer=0
                break
            else: #스택이전 값이 pair로 맞아떨어지면 그거 스택에서 제거해버리기 
                stack.pop() 
    if stack: #다 끝났는데 스택에 남아있으면 아직 pair못찾은거 존재해서 
        answer=0
    print(f'#{tc} {answer}')



            
                


            
            
            
           