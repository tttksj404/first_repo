# 아래 함수를 수정하시오.
bucket = []
def reverse_string(words):
    for one in words:
        bucket.append(one)
    bucket.reverse()
    original_bucket = "".join(bucket)  #핵심 여기서 ".join 해주면 풀로 다시 붙여준다는 느낌 "
    return  original_bucket


result = reverse_string("Hello, World!")
print(result)  # !dlroW ,olleH
