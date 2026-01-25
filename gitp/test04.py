'''
❖ 정싸피는 이번 프로젝트에서 회원가입 유효성 검사팀에 들어가게 되었다.
유효성 검사팀은 회원가입 과정에서 유저가 입력한 정보를 검사하는
프로그램을 만드는 팀이다.
❖ 신규 생성 아이디의 마지막 글자는 반드시 0부터 9 사이의 숫자로 끝나야한다.
❖ 사용자의 입력 정보인 user_data가 python의 dictionary 형태로 들어온다고 할
때, 사용자가 입력한 아이디가 위 조건을 만족하면 True, 그렇지 않으면
False를 반환하는 is_id_valid 함수를 완성하시오.
'''




############## 주의 ##############
# 입력을 받기위한 input 함수는 절대 사용하지 않습니다.
def is_id_valid(user_data):
    id_key = []
    id_long = len(user_data)
    for ind in range(id_long):
        real_ind =str(user_data[ind])
        id_key.append(real_ind)
    if id_key[id_long] >= 0 and id_key[id_long] <= 9:
    
        return True
    else:
        return False
    # 여기에 코드를 작성하여 함수를 완성합니다.


# 추가 테스트를 위한 코드 작성 가능
# 예) print(함수명(인자))

#####################################################
# 아래 코드를 삭제하는 경우 
# 모든 책임은 삭제한 본인에게 있습니다. 
############## 테스트 코드 삭제 금지 #################
user_data1 = {
    'id': 'jungssafy5',
    'password': '1q2w3e4r',
}
print(is_id_valid(user_data1)) # True


user_data2 = {
    'id': 'kimssafy!',
    'password': '1q2w3e4r',
}
print(is_id_valid(user_data2)) # False
#####################################################