# 아래 함수를 수정하시오.
def even_elements(numbers):
    
    new_list = []
    for count in numbers:
        if count % 2 ==0:
            new_list.append(count) #메커니즘은 짝수는 담아두고  홀수는 따로 다 버려버리고 거기다 extend로 다시 짝수만 담아보기 
        else:
            pass
    
    ind = 0
    while numbers: #numbers가 비지 않을동안 계속 반복하라는 것 
        numbers.pop(0)  #pop은 ()안에 인덱스 값이 들어가는거지 어떤 특정 값이 들어가는게 아니다  #pop[0]을 계속하면 한칸씩 당겨져서 계속 사라짐 
    numbers.extend(new_list)  
    return numbers
                
  
    


my_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
result = even_elements(my_list)
print(result)