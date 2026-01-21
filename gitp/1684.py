number_of_people = 0
number_of_book = 100
many_user = [{'이름' : '김시습', '나이' : 20}, {'이름' : '허균', '나이' : 26},{'이름' : '남영로', '나이' : 25},{'이름' : '임제', '나이' : 25},{'이름' : '박지원', '나이' : 25}]
name = ['김시습', '허균', '남영로', '임제', '박지원']
age = [20, 16, 52, 36, 60]
address = ['서울', '강릉', '조선', '나주', '한성부']


def increase_user():
    pass


def decrease_book(count):
    global number_of_book
    number_of_book -= count
    return number_of_book

def create_user(name, age, address):
    user={}
    user['name']= name
    user['age']= age
    user['address']= address
    return user
pack = list(map(create_user, name,age,address))


for user in pack:
    user_number = user['name'] #여기서 for는 그냥 user라는 딕셔너리의 안의 수 만큼 반복할것이기에 놔두고 새로운 변수값으로 user['name']을 주게 되면 그 수만큼
    #key의 수만큼 각 name 호출하게됨 
    print(f'{user_number}님 환영합니다 !') #그래서 print당시에는 user_number로 제대로 불러옴 



def rental_book(info):
    for name, age in info.items():
        book_count= age//10 
        decrease_book(book_count)
        print(f'{name}님이 {book_count}권의 책을 대여하였습니다.')



user_info = []
for new_users in many_user:

    name = new_users['이름']
    age = new_users['나이']
    new_dict = {name : age}
    user_info.append(new_dict)

for info in user_info:
    rental_book(info)
