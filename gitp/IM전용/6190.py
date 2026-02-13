'''

곱해서 단조 증가하는 수 찾기 -> 2개를 곱하는거니까 이건 그냥 2개 이중 for 문으로 하나 고정 후 하나 찾기로 하기
단조 증가하는 수 담아놓는 리스트 필요
곱한 결과값이 1자리 수면 그냥 단조 증가하는 수
2자리 수면 앞자리 숫자가 뒷자리 숫자보다 커야함 -> 숫자로 계산후 문자로 나눠 받기 인덱싱해서 0,1로 구분 
3자리 수 이상부터 몇 자리 수 인지 확인 후 for 문으로 idx<idx+1 인지 전부 다 확인 하기 안되면 -1출력

'''

T = int(input())
for tc in range(1,T+1):
    N = int(input())
    num_list = list(map(int, input().split()))
    #단조 담아놓는 리스트
    dan = []

    #Ai , Aj찾기
    for i in range(N):
        for j in range(i+1,N): #for 계산에서 효율성을 발휘할 수 있는 부분 생각 항상하기! 
                if num_list[i]*num_list[j]<10:
                    #dan.append(num_list[i]*num_list[j])
                    pass 
                else:
                    #곱한 단조 값을 문자열로 나눠서 각각 처음 인덱스 부터 비교 필요
                    search = list(map(int, str(num_list[i]*num_list[j])))
                    for idx in range(len(search)-1):
                        if int(search[idx])<=int(search[idx+1]): #예외의 경우 판단 주의 !!!
                            if idx==len(search)-2:
                                dan.append(num_list[i]*num_list[j])
                            else:
                                pass
                            
                        else:
                            break #해당 곱한 단조 값은 조건 충족 안하므로 단조 아니라 버림
    
    if dan ==[]:
        print(f'#{tc} -1')
    else:
        ans = max(dan)
        print(f'#{tc} {ans}')
    

    
                
            





