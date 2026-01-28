black_list = [
    'Hoeger LLC',
    'Keebler LLC',
    'Yost and Sons',
    'Johns Group',
    'Romaguera-Crona',
]

censored_user_list = {}



def create_user(user_list):
    censored_value = []
    for user in user_list:
        censored_value.append(user)
    for number in range(len(censored_value)): #range 넣어주는거 잊지 않기 #range 범위 주의 
        censored_user_list[Key]=censored_value[number]
    return censored_user_list



def censorship(company_name):
    if company_name in black_list:
        print(f'{company_name}소속의 {censored_user_list[company_name]}은/는 등록할 수 없습니다.') #딕셔너리에서 값 꺼낼땐 []대괄호로 꺼내기 
        del censored_user_list[company_name]
        return False
    else:
        print("이상 없습니다.")
        return True




print(censored_user_list)