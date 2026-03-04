# 아래 클래스를 수정하시오.
class StringRepeater:

    @staticmethod
    def repeat_string(repeat_number, repeat_text):
        for a in range(repeat_number):
            print(repeat_text)

repeater1 = StringRepeater()
repeater1.repeat_string(3, "Hello")