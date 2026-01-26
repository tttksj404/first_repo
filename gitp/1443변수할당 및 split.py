# 아래 함수를 수정하시오.
def capitalize_words(words):
    real_words=words.split(',') #,를 기점으로 나눠주기 
    first_sentence= real_words[0] # 나눠주는데 인덱스 첫번째 두번째로 나눠줌 
    second_sentence= real_words[1]

    
    f= str.title(first_sentence)  #이렇게 했으면 변수를 할당 해줘야 진행이 된다. 
    s =str.title(second_sentence) #마찬가지임 
    a=f +','+s  #여기서 할당된 값으로 해줘야 들어감 
    return a 




result = capitalize_words("hello, world!")
print(result)
