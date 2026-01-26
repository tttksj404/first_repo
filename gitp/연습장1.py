def is_id_valid(user_data):
    # 1. 딕셔너리에서 'id' 값 추출
    user_id = user_data.get('id', '')
    
    # 2. 아이디가 비어있을 경우에 대한 예외 처리
    if not user_id:
        return False
    
    # 3. 마지막 글자([-1])가 숫자인지(isdecimal) 확인하여 결과(True/False)를 즉시 반환
    return user_id[-1].isdecimal()

#####################################################
# 테스트 코드 (수정 금지 영역)
user_data1 = {
    'id': 'jungssafy5',
    'password': '1q2w3e4r',
}
print(f"테스트 1 결과: {is_id_valid(user_data1)}") # True

user_data2 = {
    'id': 'kimssafy!',
    'password': '1q2w3e4r',
}
print(f"테스트 2 결과: {is_id_valid(user_data2)}") # False
#####################################################