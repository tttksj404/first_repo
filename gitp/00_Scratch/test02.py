'''
김싸피는 시험점수를 관리하는 코드를 작성하려고 한다.
❖ 전체 점수 중 60점 미만인 과목의 개수를 계산하여 반환하는 under_60 함수를 완성하시오.
'''
############## 주의 ##############
# 입력을 받기위한 input 함수는 절대 사용하지 않습니다.
'''
def under_60(scores):
    unpassed = []
    count_number = 0
    m = len(scores)
    for ind in range(m):
        if scores[ind] < 60:
            unpassed.append(scores[ind]) #이건 그 값을 넣는 용도고
            count_number +=1 #실제로 몇개가 들어갔는지는 변수값 초기화로 넣어주면됨 
        else:
            pass
    return count_number
'''
def under_60(scores):
    total_length = len(scores)
    count_number = 0
    for ind in range(total_length):
        if scores[ind] < 60:
            count_number +=1
    return count_number


    # 여기에 코드를 작성하여 함수를 완성합니다.


# 추가 테스트를 위한 코드 작성 가능
# 예) print(함수명(인자))

#####################################################
# 아래 코드를 삭제하는 경우 
# 모든 책임은 삭제한 본인에게 있습니다. 
############## 테스트 코드 삭제 금지 #################
print(under_60([30, 60, 90, 70])) # 1
print(under_60([0, 10, 20, 30, 40, 50])) # 6
print(under_60([50, 70, 50, 45, 80, 80])) # 3
#####################################################
