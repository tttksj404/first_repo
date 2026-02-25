'''
N//2 해서 나오는 값 -1 인 인덱스 까지가 나눠질 부분 
N이 짝수면 그대로 나누면 되는거고
N이 홀수면 round(N//2)해서 올림하고 -1 까지  인덱스로 나누기
그래서 첫번째 부분 인덱스는 1,3,5 홀
두번째 부분들은 2,4,6 짝 인덱스로 들어감 
그렇게 추가된 값들 가지고 나열
0,1,2->0,2,4
'''
T= int(input())
for tc in range(1,T+1):
    N=int(input())
    num_list = list(map(str,input().split()))
    answer_list=[0]*N
    
    if N%2==0:#짝수면
        first=num_list[:N//2]
        second=num_list[N//2:]
        for i in range(N//2):
            answer_list[2*i]=first[i]
        for j in range(N//2):#3,4,5 ->1,3,5
            answer_list[1+2*j]=second[j]
    else:
        first=num_list[:(N//2)+1]#3개 0,1,2
        second=num_list[(N//2)+1:]#2개 3,4
        for a in range(len(first)):
            answer_list[2*a]=first[a]
        for b in range(len(second)):
            answer_list[1+2*b]=second[b]
    print(f'#{tc}',*answer_list)




