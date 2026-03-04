# 아래 함수를 수정하시오.
def check_number(n):
    if type(n) is str:
        print(f'숫자를 입력하세요: {n}')
        print("잘못된 입력입니다.")
    if type(n) is int:
        if n >0:
            print(f'숫자를 입력하세요: {n}')
            print("양수입니다.")
        elif n==0:
            print(f'숫자를 입력하세요: {n}')
            print("0입니다.")
        elif n<0:
            print(f'숫자를 입력하세요: {n}')
            print("음수입니다.")
   
        


check_number("a")
