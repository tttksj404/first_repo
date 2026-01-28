number_of_book = 100
name = ['김시습', '허균', '남영로', '임제', '박지원']
age = [20, 16, 52, 36, 60]
address = ['서울', '강릉', '조선', '나주', '한성부']

# 1. 책의 수를 줄이는 함수
def decrease_book(count):
    global number_of_book
    number_of_book -= count
    return number_of_book

# 2. 유저 정보를 딕셔너리로 만드는 함수
def create_user(name, age, address):
    return {'name': name, 'age': age, 'address': address}

# 3. map을 사용하여 유저 목록(pack) 생성
pack = list(map(create_user, name, age, address))

# 4. 모든 유저에게 환영 인사 (첫 번째 루프)
for user in pack:
    print(f"{user['name']}님 환영합니다 !")

# 5. 책 대여 시스템 함수
def rental_book(user):
    target_name = user['name']
    target_age = user['age']
    
    # 나이를 10으로 나눈 몫만큼 대여
    book_count = target_age // 10 
    decrease_book(book_count)
    
    print(f'남은 책의 수 : {number_of_book}')
    print(f'{target_name}님이 {book_count}권의 책을 대여하였습니다.')

# 6. 각 유저별로 대여 진행 (두 번째 루프)
for info in pack:
    rental_book(info)
