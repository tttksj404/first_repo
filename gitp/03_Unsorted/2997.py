def restructure_word(word, arr):
    for words in original_word:
        arr.append(words)
    print(arr)
    for delet in word:
        if delet.isdecimal() is True:  #변수 값은 그 범위 내에서 잡기 
            for _ in range(int(delet)):
                arr.pop()
        else:
            arr.remove(delet)
    return arr


        


    

original_word = '코딩 공부는ㄴ 1일ㄹ 1커ㅓ밋ㅅ @@@#^()#_+!&~:"'
word = '1ㄴ2ㄹ3ㅓ4ㅅ5'
arr = []

result = restructure_word(word, arr)
final = "".join(result)
print(arr)
print(final)

