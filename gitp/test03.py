#❖ 정싸피는 이번 프로젝트에서 회원가입 유효성 검사팀에 들어가게 되었다.
#유효성 검사팀은 회원가입 과정에서 유저가 입력한 정보를 검사하는
#프로그램을 만드는 팀이다.
#❖ 신규 아이디 생성 시 아이디와 비밀번호 모두 빈 값이 입력되는 것을
#방지하고자 한다.
#❖ 사용자의 입력 정보인 user_data가 python의 dictionary 형태로 들어온다고 할
#때, 사용자가 입력한 아이디와 비밀번호 중 하나라도“비어있는 문자열”이면
#False, 그렇지 않으면 True를 반환하는 is_user_data_valid 함수를 완성하시오.



############## 주의 ##############
# 입력을 받기위한 input 함수는 절대 사용하지 않습니다.
def is_user_data_valid(user_data):
    if user_data['id'] == '' or user_data['password'] == '':
        return False
    else:
        return True
    # 여기에 코드를 작성하여 함수를 완성합니다.


# 추가 테스트를 위한 코드 작성 가능
# 예) print(함수명(인자))

#####################################################
# 아래 코드를 삭제하는 경우 
# 모든 책임은 삭제한 본인에게 있습니다. 
############## 테스트 코드 삭제 금지 #################
user_data1 = {
    'id': '',
    'password': '1q2w3e4r',
}
print(is_user_data_valid(user_data1)) # False 


user_data2 = {
    'id': 'jungssafy',
    'password': '1q2w3e4r',
}
print(is_user_data_valid(user_data2)) # True
#####################################################