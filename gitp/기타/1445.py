# 아래 함수를 수정하시오.
def count_character(character1, character2):
    many = str.count(character1, character2)
    return many
    


result = count_character("Hello, World!", "o")
print(result)  # 2
