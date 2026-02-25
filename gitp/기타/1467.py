class UserInfo:
    def __init__(self):
        # 사용자 정보를 저장할 딕셔너리 초기화
        self.user_data = {}

    def get_user_info(self):
        # 1. 이름 입력 받기
        name = input("이름을 입력하세요: ")
        
        # 이름이 비어있거나 공백인 경우 None 반환
        if not name.strip():
            return None

        # 2. 나이 입력 받기
        age_input = input("나이를 입력하세요: ")
        
        try:
            # 나이를 정수로 변환 시도
            age = int(age_input)
            
            # 이름과 나이가 올바르면 딕셔너리에 저장
            self.user_data = {"이름": name, "나이": age}
            return True
            
        except ValueError:
            if type(age_input) is str:
            # 정수 변환 실패(미입력 포함) 시 메시지 출력 후 False 반환
                print(f'이름을 입력하세요 : {name}')
                print(f'나이를 입력하세요 : {age_input}')
                print("나이는 숫자로 입력해야 합니다.")
                return False
            

    def display_user_info(self):
        # 딕셔너리가 비어있는지 확인
        if not self.user_data:
            print(f'이름을 입력하세요 : ')
            print("사용자 정보가 입력되지 않았습니다.")
        else:
            # 저장된 정보 출력
            print(f'이름을 입력하세요 : {self.user_data['이름']}')
            print(f'나이를 입력하세요 : {self.user_data['나이']}')
            print(f"이름: {self.user_data['이름']}")
            print(f"나이: {self.user_data['나이']}")

# 아래 코드는 수정하지 마세요.
user = UserInfo()
result = user.get_user_info()

if result is True:
    user.display_user_info()
elif result is None:
    user.display_user_info()