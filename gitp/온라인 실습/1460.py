class Person:
    # 1. 클래스 변수 선언 (모든 인스턴스가 공유함)
    number_of_people = 0
    
    def __init__(self, name, age):
        self.name = name
        self.age = age
        # 2. 인스턴스가 생성될 때마다 클래스 변수 1 증가
        Person.number_of_people += 1
    
    def introduce(self):
        print(f'안녕하세요, {self.name}입니다. 나이는 {self.age}살입니다.')

# 테스트
person1 = Person("Alice", 25)
person1.introduce()
print(Person.number_of_people)  # 출력 결과: 2