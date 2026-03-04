number_of_people = 0


def increase_user(current_count):
    return current_count +1
current_count = 0




def create_user(name, age, address):
    user={}
    user['name']= name
    user['age']= age
    user['address']= address
    return user
    


name = ['김시습', '허균', '남영로', '임제', '박지원']
age = [20, 16, 52, 36, 60]
address = ['서울', '강릉', '조선', '나주', '한성부']
pack = list(map(create_user, name,age,address))

for user in pack:
    user_number = user['name'] #여기서 for는 그냥 user라는 딕셔너리의 안의 수 만큼 반복할것이기에 놔두고 새로운 변수값으로 user['name']을 주게 되면 그 수만큼
    #key의 수만큼 각 name 호출하게됨 
    print(f'{user_number}님 환영합니다 !') #그래서 print당시에는 user_number로 제대로 불러옴 




print(pack) #pack 불러오면 딕셔너리로 이뤄진 리스트 값 전체를 불러오게 된다. 
