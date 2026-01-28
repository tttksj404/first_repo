number_of_book = 100


def decrease_book(amount):
    global number_of_book
    number_of_book -=amount
    
    print(f'남은 책의 수 : {number_of_book}')

def rental_book(name, numbers):
    name = "홍길동"
    numbers = 3
    decrease_book(numbers)
    print(f'{name}님이 {numbers}권의 책을 대여하였습니다.')
    


rental_book("홍길동",3)