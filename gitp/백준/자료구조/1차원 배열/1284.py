#리스트-> len값으로 총 길이에다가 +1된 값이 1cm 의 여백개수
#1= 2cm /0=4cm / 나머지는 3cm. 
#while로 input 받고 break if 조건으로 0나오기 전까지

while True:
    number = input()
    if int(number) == 0: #여기도 문자열 vs 숫자 형태 주의 
        break

    blank_length = len(str(number))+1 
    each_length = int(0)
    
    for num in number: #여기서 문자열 타입이라서 1과 ==비교시 항상 false나와 
        #else로 무조건 빠지게 되기에 항상 int, str 바꿔주고 들어가기 
        if num == '1':   
            each_length+=2              
        elif num == '0':
            each_length+=4
        else:
            each_length+=3
    total_num = each_length +blank_length

    print(total_num)




    