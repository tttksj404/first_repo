# 아래 함수를 수정하시오.
def sort_tuple(numbers):
    change = list(numbers)  #sorted 함수는 어떤 자료형이든 정렬되서 리스트로 바꾸고 정렬시키고 revered한다음 
    #다음 듀플로 바꾸면 되긴함 
    #but 아래는 버블 정렬로 앞과 뒤의 순서를 끊임없이 바꿔서 순서 정렬시킴 큰걸 앞으로 뺴는 것 

    min_numbers = 0
    ind = 0
    for ind1 in range(len(change)-1):
        for ind2 in range(len(change)-1):
            if change[ind2] < change[ind2+1]:
                change[ind2], change[ind2+1] = change[ind2+1], change[ind2]
    switch=reversed(change)    
    answer = tuple(switch)
    
    return answer

    
    
    
   


result = sort_tuple((5, 2, 8, 1, 3))
print(result)
