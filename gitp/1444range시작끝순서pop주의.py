# 아래 함수를 수정하시오.
def even_elements(numbers):
    
    new_list = []
    for count in numbers:
        if count % 2 ==0:
            new_list.append(count) #메커니즘은 짝수는 담아두고  홀수는 따로 다 버려버리고 거기다 extend로 다시 짝수만 담아보기 
        else:
            pass
    
    ind = 0
    for ind in range(len(numbers)-1,-1,-1):   #pop을 순서대로 하면 인덱스 순서가 계속바뀌어서 반복시 인덱스값을 못찾게된다 / range(시작, 끝, step)
        #range(끝은 항상 미만이기에 거꾸로 되면 시작 값에는 -1 하고 끝 값에도 원래 시작값의 -1 해줘야 제대로 돌아감 )
        numbers.pop(ind)  #pop은 ()안에 인덱스 값이 들어가는거지 어떤 특정 값이 들어가는게 아니다 
    numbers.extend(new_list)  
    return numbers
                
  
    


my_list = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
result = even_elements(my_list)
print(result)
