#각 대각선 구하는 식 써서 각 대각선에서의 합, 행끼리의 합, 열끼리의 합 중에서 최대값 도출하면됨

'''
i, j 의 크기에 따라 접근하는 원소 비교(NXN 배열)
i<j 3x3에서 ㄱ자오른쪽 3칸
i>j ㄴ자 왼쪽 3칸 
i == j 왼쪽대각선 3칸
N-1-i == j 오른쪽 대각선 3칸  
'''

count = 0
answer_sum = []
each_i_sum = [] #행
each_j_sum = [] #열 
cross_left_sum = []
cross_right_sum = []

for a in range(1,11):
    cross_left_sum=[] #초기화는 반복문의 초반에 해줘야 무리가 없음 중간중간 해주려하면 안됨 
    cross_right_sum=[]
    answer_sum = [] #초기화 매우중요 ! 
    count = int(input())
    input_data = [list(map(int, input().split())) for _ in range(100)] #2차원배열로 리스트 구성해야해서 리스트 컴프리헨션 걸고 100번으로 반복해서 100x100만들어주기


    for i in range(100):
        each_i_sum =[]
        for j in range(100):
            each_i_sum.append(input_data[i][j])
            if i==j:
                cross_left_sum.append(input_data[i][j]) #왼쪽 대각선 모음
            elif 99-i ==j: 
                cross_right_sum.append(input_data[i][j]) #오른쪽 대각선 모음
        
        i_sum = sum(each_i_sum)  
        answer_sum.append(i_sum) #여기서 각 대각선 및 세로 가로 값모음에 대한 sum을 담아주는 것 
    lcross_sum = sum(cross_left_sum)
    rcross_sum = sum(cross_right_sum)
    answer_sum.append(lcross_sum)
    answer_sum.append(rcross_sum)

    for j in range(100):
        each_j_sum =[]
        for i in range(100):
            each_j_sum.append(input_data[i][j])
        j_sum = sum(each_j_sum)
        answer_sum.append(j_sum)
    real_answer = max(answer_sum)
    print(f'#{a} {real_answer}')






