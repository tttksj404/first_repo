data_1 = 'qweqwYadnOyjnsaU4trwg asjnaAn245krRmkfE 42grTasdnHasdnvEasdn asdevadnBasdanEsdkqefqefvaSasdqaeeqqvedwt5hfbsdT24tewfd'



'''

예시코드
arr = [1, 2, 3, 4, 5]
for num in arr:
    print(num, end='')
출력결과 : 12345
'''
# 아래에 코드를 작성하시오.
storage = []

for num in data_1:
    if num.isupper() or num == ' ':
        print(num, end="") #선정된걸 계속 반복 출력해주니까 
print()



data_2 = '걉파반샤팝다푸거맥파바자들퍼바배들밥샵파누타히매니배사바파힘다브사부힙헤베내테치대내'
arr = []
# 아래에 코드를 작성하시오.
target = "내힘들다"
for num in target:   #여기서 data_2를 가져갈게 아니라 target안에서 가져가고 if 문을 생략가능함 #거기다 for를 data_2가 아닌 target안에서만 반복하면 그것만 찾음 
    #더 확실한 방법 
    numbers = data_2.find(num)
    arr.append(numbers)
print(arr)
arr.sort()
print(arr)

for key_word in arr:
    a=list(data_2)[key_word] #인덱스 써야하는건 반드시 리스트화 시켜주기 
    print(a, end="")
