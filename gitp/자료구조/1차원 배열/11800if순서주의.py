#테스트 개수 t 
#테스트 개수에 따른 두수 a,b
'''
1 : "Yakk"
2 : "Doh"
3 : "Seh"
4 : "Ghar"
5 : "Bang"
6 : "Sheesh"

1 - 1 : "Habb Yakk"    
2 - 2 : "Dobara" 
3 - 3 : "Dousa"
4 - 4 : "Dorgy"
5 - 5 : "Dabash"
6 - 6 : "Dosh"

예외 
5-6 "Sheesh Beesh"
6-5 "Sheesh Beesh"
'''



T = int(input())
for n in range(T):
    a,b = map(int, input().split())
    a_dict = {}
    b_dict = {}
    
    if a <= 1:
        a_dict[a] = "Yakk"
    elif a <=2:
        a_dict[a] = "Doh"
    elif a <=3:
        a_dict[a] = "Seh"
    elif a<=4:
        a_dict[a] = "Ghar"
    elif a<=5:
        a_dict[a] = "Bang"
    else: 
        a_dict[a] = "Sheesh"
    
    if b <= 1:
        b_dict[b] = "Yakk"
    elif b <=2:
        b_dict[b] = "Doh"
    elif b <=3:
        b_dict[b] = "Seh"
    elif b <=4:
        b_dict[b] = "Ghar"
    elif b <=5:
        b_dict[b] = "Bang"
    else:
        b_dict[b]= "Sheesh"

    if  b>a:
        answer = b_dict[b] +" "+a_dict[a]
    elif a>b:
        answer = a_dict[a] +" "+b_dict[b]  #이부분과 맨 아래에 있는 if 충돌가능성 존재 
   
    elif a==b:
        if a==1:
            answer = "Habb Yakk"
        elif a==2:
            answer = "Dobara"
        elif a==3:
            answer = "Dousa"
        elif a==4:
            answer = "Dorgy"
        elif a==5:
            answer = "Dabash"
        else:
            answer = "Dosh"
    if a == 5 and b ==6:
        answer = "Sheesh Beesh"
    if a == 6 and b ==5:
        answer = "Sheesh Beesh" #예외의 예외는 마지막에 처리해야됨 
        #if로 순서중요하기에 생각하기
    
    
    n+=1
    print(f'Case {n}: {answer}')
    n-=1
    







