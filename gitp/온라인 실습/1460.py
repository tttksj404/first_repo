# 아래 클래스를 수정하시오.
class Person:
    def __init__(self,name,age):
        self.name = name
        self.age = age
    
    def introduce(self):
        print(f'안녕하세요, {self.name}입니다. 나이는 {self.age}살입니다.')


person1 = Person("Alice", 25)
person1.introduce()
print(Person.number_of_people)
