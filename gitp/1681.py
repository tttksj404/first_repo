number_of_people = 0


def increase_user(current_count):
    return current_count +1 
current_count = 0
print(f'현재 가입 된 유저 수 : {current_count}')    


def create_user(name, age, address):
    user_info = {}
    user_info['name']= name
    user_info['age']= age
    user_info['address']=address
    return user_info



current_user = create_user('홍길동', 30 , '서울')
number_of_people = increase_user(number_of_people)
print(f"{current_user['name']}님 환영합니다!")
print(current_user)
print(f'현재 가입 된 유저 수 : {number_of_people}')

