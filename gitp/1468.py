# 아래 함수를 수정하시오.
def remove_duplicates(numbers):
    new_lst = []
    new= set(numbers) #set으로 중복 제거 
    for number_count in new:
        new_lst.append(number_count)

    return new_lst


result = remove_duplicates([1, 2, 2, 3, 4, 4, 5])
print(result)
